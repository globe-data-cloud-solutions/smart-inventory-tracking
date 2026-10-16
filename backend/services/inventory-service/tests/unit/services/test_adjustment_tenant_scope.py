"""Adjustment and count-session lookups by id are tenant-filtered.

An adjustment or count session that belongs to another tenant answers the
same 404 as a missing id ("Adjustment not found" / "Count session not
found") — never 403, so the id's existence elsewhere is not revealed — and
nothing is written: no adjustment_orders UPDATE, no ledger entry.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from fastapi import HTTPException

TENANT_A   = "10000000-0000-0000-0000-00000000000a"
TENANT_B   = "10000000-0000-0000-0000-00000000000b"
WAREHOUSE  = "20000000-0000-0000-0000-000000000001"
PRODUCT    = "40000000-0000-0000-0000-000000000001"
ADJ_ID     = UUID("aaaaaaaa-0000-0000-0000-000000000001")
SESSION_ID = UUID("bbbbbbbb-0000-0000-0000-000000000001")


@dataclass
class _User:
    user_id: str
    tenant_id: str
    warehouse_id: str | None
    region_id: str | None
    role: str


TA_A = _User("u-ta-a", TENANT_A, None, None, "TA")
TA_B = _User("u-ta-b", TENANT_B, None, None, "TA")


def _adjustment(status: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=ADJ_ID, tenant_id=TENANT_A, status=status,
        product_id=UUID(PRODUCT), warehouse_id=UUID(WAREHOUSE),
        quantity_delta=Decimal("5"), reason_code="DAMAGE",
        created_by="u-creator", product_override_applied=False,
        required_approver_user_id=None, required_approver_name=None,
        approver_escalated=False, lot_id=None, lot_number=None,
        expiry_date=None, auto_lot=False, is_self_approved=False, total_value=None,
    )


def _count_session() -> SimpleNamespace:
    return SimpleNamespace(
        id=SESSION_ID, tenant_id=TENANT_A, warehouse_id=UUID(WAREHOUSE), status="OPEN",
    )


class _World:
    """Tenant A's adjustment and count session. A lookup by id finds the row;
    a tenant_id = :tid filter drops it for any other tenant. (Without the
    filter the row comes back — the bug these tests pin.)"""

    def __init__(self, adjustment: SimpleNamespace | None = None) -> None:
        self.adjustment = adjustment
        self.session = _count_session()
        self.updates: list[tuple[str, dict]] = []

    @staticmethod
    def _visible(row: Any, sql: str, params: dict) -> bool:
        return row is not None and params.get("id") == str(row.id) and (
            "tenant_id = :tid" not in sql or params.get("tid") == str(row.tenant_id)
        )

    async def execute(self, stmt: Any, params: dict | None = None) -> MagicMock:
        sql, params = " ".join(str(stmt).split()), params or {}
        if sql.startswith("UPDATE adjustment_orders"):
            self.updates.append((sql, params))
            return MagicMock()
        if "FROM adjustment_orders WHERE id = :id" in sql:
            row = self.adjustment if self._visible(self.adjustment, sql, params) else None
            return MagicMock(fetchone=MagicMock(return_value=row))
        if "FROM adjustment_orders ao" in sql and "p.batch_tracking" in sql:
            # Non-batch product: no lot to resolve at posting.
            return MagicMock(fetchone=MagicMock(return_value=None))
        if "FROM count_sessions WHERE id = :id" in sql:
            row = self.session if self._visible(self.session, sql, params) else None
            return MagicMock(fetchone=MagicMock(return_value=row))
        raise AssertionError(f"unexpected query: {sql}")

    def db(self) -> AsyncMock:
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=self.execute)
        return session


@pytest.fixture
def ledger():
    """record_transaction, write_to_outbox and audit_log, patched where the service calls them."""
    with patch("services.inventory_service.record_transaction",
               new=AsyncMock(return_value="eeeeeeee-0000-0000-0000-000000000001")) as rec, \
         patch("services.inventory_service.write_to_outbox", new=AsyncMock()), \
         patch("services.inventory_service.audit_log", new=AsyncMock()):
        yield rec


def _first_sql(db: AsyncMock) -> tuple[str, dict]:
    call = db.execute.call_args_list[0]
    return " ".join(str(call.args[0]).split()), call.args[1]


# DRAFT → PENDING_APPROVAL / CANCELLED; PENDING_APPROVAL → REJECTED / APPROVED.
_TRANSITIONS = [
    ("DRAFT", "PENDING_APPROVAL"),
    ("PENDING_APPROVAL", "REJECTED"),
    ("DRAFT", "CANCELLED"),
    ("PENDING_APPROVAL", "APPROVED"),
]


@pytest.mark.unit
class TestTransitionAdjustmentTenantFilter:

    @pytest.mark.parametrize(
        "status,next_state", _TRANSITIONS, ids=[t for _, t in _TRANSITIONS],
    )
    async def test_other_tenant_is_404_and_nothing_written(
        self, ledger, status, next_state,
    ) -> None:
        from services.inventory_service import InventoryService

        world = _World(_adjustment(status))
        db = world.db()
        with pytest.raises(HTTPException) as exc:
            await InventoryService(db).transition_adjustment(TA_B, ADJ_ID, next_state)

        assert exc.value.status_code == 404
        assert exc.value.detail == "Adjustment not found"
        sql, params = _first_sql(db)
        assert "tenant_id = :tid" in sql
        assert params["tid"] == TENANT_B
        assert world.updates == []
        ledger.assert_not_awaited()

    async def test_same_tenant_transition_still_works(self, ledger) -> None:
        from services.inventory_service import InventoryService

        world = _World(_adjustment("DRAFT"))
        result = await InventoryService(world.db()).transition_adjustment(
            TA_A, ADJ_ID, "CANCELLED",
        )

        assert result.status == "CANCELLED"
        (sql, params), = world.updates
        assert "WHERE id = :id AND tenant_id = :tid" in sql
        assert params == {"s": "CANCELLED", "id": str(ADJ_ID), "tid": TENANT_A}
        ledger.assert_not_awaited()


@pytest.fixture
def route_gates():
    """The permission and contract-stage gates in front of the approve route."""
    from shared.permissions.middleware import PermissionResult

    with patch("shared.permissions.middleware.check_permission",
               new=AsyncMock(return_value=PermissionResult(allowed=True))), \
         patch("shared.billing.contract_stage.get_tenant_contract_stage",
               AsyncMock(return_value={"stage": "ACTIVE", "contract_end": None,
                                       "read_only_since": None})):
        yield


@pytest.mark.unit
class TestApproveRouteTenantFilter:

    async def test_other_tenant_pre_read_is_404_and_no_ledger(self, route_gates, ledger) -> None:
        from routers.adjust import approve_adjustment

        world = _World(_adjustment("PENDING_APPROVAL"))
        db = world.db()
        with pytest.raises(HTTPException) as exc:
            await approve_adjustment(adjustment_id=ADJ_ID, user=TA_B, db=db)

        assert exc.value.status_code == 404
        assert exc.value.detail == "Adjustment not found"
        sql, params = _first_sql(db)
        assert "tenant_id = :tid" in sql
        assert params["tid"] == TENANT_B
        assert world.updates == []
        ledger.assert_not_awaited()

    async def test_same_tenant_approve_posts(self, route_gates, ledger) -> None:
        from routers.adjust import approve_adjustment

        world = _World(_adjustment("PENDING_APPROVAL"))
        resp = await approve_adjustment(adjustment_id=ADJ_ID, user=TA_A, db=world.db())

        assert resp.data.status == "POSTED"
        ledger.assert_awaited_once()
        assert ledger.await_args.kwargs["tenant_id"] == TENANT_A
        assert [p for _, p in world.updates] == [
            {"s": "APPROVED", "id": str(ADJ_ID), "tid": TENANT_A},
            {"id": str(ADJ_ID), "tid": TENANT_A},
        ]


@pytest.mark.unit
class TestCountSessionTenantFilter:

    async def test_other_tenant_is_404(self) -> None:
        from services.inventory_service import InventoryService

        db = _World().db()
        with pytest.raises(HTTPException) as exc:
            await InventoryService(db).get_count_session(TA_B, SESSION_ID)

        assert exc.value.status_code == 404
        assert exc.value.detail == "Count session not found"
        sql, params = _first_sql(db)
        assert "tenant_id = :tid" in sql
        assert params["tid"] == TENANT_B

    async def test_same_tenant_still_works(self) -> None:
        from services.inventory_service import InventoryService

        result = await InventoryService(_World().db()).get_count_session(TA_A, SESSION_ID)
        assert (result.session_id, result.status) == (SESSION_ID, "OPEN")
