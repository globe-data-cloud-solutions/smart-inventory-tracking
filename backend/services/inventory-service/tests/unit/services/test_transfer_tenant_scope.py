"""Transfer lookups by id are tenant-filtered, and transfer list / detail are
scoped to the caller's node subtree (RB-2).

A transfer that belongs to another tenant answers 404 "Transfer not found",
exactly as a missing id does — get_transfer and transition_transfer alike.
A same-tenant transfer outside the caller's subtree is left out of the list
and answers 403 TRANSFER_OUT_OF_SCOPE on detail.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from fastapi import HTTPException

TENANT_A = "10000000-0000-0000-0000-00000000000a"
TENANT_B = "10000000-0000-0000-0000-00000000000b"
WAREHOUSE_A = "20000000-0000-0000-0000-000000000001"
WAREHOUSE_B = "20000000-0000-0000-0000-000000000002"
TRANSFER_ID = UUID("cccccccc-0000-0000-0000-000000000001")


@dataclass
class _User:
    user_id: str
    tenant_id: str
    warehouse_id: str | None
    region_id: str | None
    role: str


def _transfer_row(tenant_id: str = TENANT_A) -> MagicMock:
    row = MagicMock()
    row.id = TRANSFER_ID
    row.tenant_id = tenant_id
    row.transfer_type = "PULL"
    row.status = "DRAFT"
    row.from_warehouse_id = WAREHOUSE_A
    row.to_warehouse_id = WAREHOUSE_B
    row.is_self_approved = False
    row.reference_number = "TR-0001"
    row.from_warehouse_name = "Source"
    row.to_warehouse_name = "Destination"
    row.created_at = datetime(2026, 9, 1, tzinfo=timezone.utc)
    return row


def _db(row: MagicMock) -> AsyncMock:
    """A session holding one transfer that behaves like the table: a lookup by
    id finds it, and a tenant_id = :tid filter drops it for any other tenant.
    (Without the filter the row comes back — the bug these tests pin.)"""

    async def execute(stmt: Any, params: dict | None = None) -> MagicMock:
        sql, params = str(stmt), params or {}
        if "FROM transfer_orders WHERE id = :id" in sql or "WHERE to_.id = :id" in sql:
            found = params.get("id") == str(row.id) and (
                "tenant_id = :tid" not in sql or params.get("tid") == str(row.tenant_id)
            )
            return MagicMock(fetchone=MagicMock(return_value=row if found else None))
        raise AssertionError(f"unexpected query: {sql}")

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=execute)
    return session


OTHER_TENANT_TA = _User("u-ta-b", TENANT_B, None, None, "TA")


@pytest.mark.unit
class TestTransferLookupTenantFilter:
    async def test_get_transfer_other_tenant_is_404(self) -> None:
        from services.inventory_service import InventoryService

        with pytest.raises(HTTPException) as exc:
            await InventoryService(_db(_transfer_row())).get_transfer(OTHER_TENANT_TA, TRANSFER_ID)
        assert exc.value.status_code == 404
        assert exc.value.detail == "Transfer not found"

    async def test_transition_transfer_other_tenant_is_404(self) -> None:
        from services.inventory_service import InventoryService

        with pytest.raises(HTTPException) as exc:
            await InventoryService(_db(_transfer_row())).transition_transfer(
                OTHER_TENANT_TA,
                TRANSFER_ID,
                "PENDING_REVIEW",
            )
        assert exc.value.status_code == 404
        assert exc.value.detail == "Transfer not found"

    async def test_missing_id_gives_the_same_404(self) -> None:
        """Same tenant, different id — indistinguishable from the cross-tenant case."""
        from services.inventory_service import InventoryService

        same_tenant_ta = _User("u-ta-a", TENANT_A, None, None, "TA")
        with pytest.raises(HTTPException) as exc:
            await InventoryService(_db(_transfer_row())).get_transfer(
                same_tenant_ta,
                UUID("cccccccc-0000-0000-0000-0000000000ff"),
            )
        assert exc.value.status_code == 404
        assert exc.value.detail == "Transfer not found"


# ── Node-subtree scoping for list and detail (RB-2) ──────────────────────────
#
#   REGION ─┬─ WH_A
#           └─ WH_B          WH_C, WH_D, WH_E sit outside REGION
#
#   T_AB  WH_A -> WH_B   (from end in WH_A's subtree)
#   T_CA  WH_C -> WH_A   (to end in WH_A's subtree)
#   T_CD  WH_C -> WH_D   (outside REGION)

REGION = "30000000-0000-0000-0000-0000000000aa"
WH_A = "30000000-0000-0000-0000-00000000000a"
WH_B = "30000000-0000-0000-0000-00000000000b"
WH_C = "30000000-0000-0000-0000-00000000000c"
WH_D = "30000000-0000-0000-0000-00000000000d"
WH_E = "30000000-0000-0000-0000-00000000000e"

T_AB = UUID("dddddddd-0000-0000-0000-0000000000ab")
T_CA = UUID("dddddddd-0000-0000-0000-0000000000ca")
T_CD = UUID("dddddddd-0000-0000-0000-0000000000cd")

_CREATED_AT = datetime(2026, 9, 1, 8, 30, tzinfo=timezone.utc)

# Subtrees as get_descendant_node_ids returns them — upper-cased on purpose:
# the scope check must lowercase both sides.
_SUBTREES = {
    REGION: {REGION.upper(), WH_A.upper(), WH_B.upper()},
    WH_A: {WH_A.upper()},
    WH_E: {WH_E.upper()},
}


async def _descendants(db: Any, tenant_id: str, node_id: str) -> set[str]:
    return _SUBTREES[node_id]


def _scoped_row(transfer_id: UUID, from_wh: str, to_wh: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=transfer_id,
        transfer_id=transfer_id,
        tenant_id=TENANT_A,
        transfer_type="PULL",
        status="DRAFT",
        from_warehouse_id=UUID(from_wh),
        from_warehouse_name=f"name-{from_wh[-2:]}",
        to_warehouse_id=UUID(to_wh),
        to_warehouse_name=f"name-{to_wh[-2:]}",
        created_by="u-creator",
        created_by_authority_level=4,
        created_at=_CREATED_AT,
        updated_at=_CREATED_AT,
        is_self_approved=False,
        current_approval_step=1,
        resolved_approval_steps=None,
        reference_number=f"TR-{str(transfer_id)[-2:].upper()}",
    )


def _names_caller(row: Any, params: dict) -> bool:
    """The approver EXISTS clause, emulated independently of the service code:
    a step node in :step_nodes, or :uid as assignee or in all_holders."""
    nodes, uid = set(params["step_nodes"]), params["uid"]
    for step in row.resolved_approval_steps or []:
        if (step.get("node_id") or "").lower() in nodes:
            return True
        if (step.get("assigned_to_user_id") or "").lower() == uid:
            return True
        if any(h["user_id"].lower() == uid for h in step.get("all_holders") or []):
            return True
    return False


class _World:
    """Tenant A's transfers. The list query honours ANY(:subtree); the by-id
    lookup honours tenant_id = :tid."""

    def __init__(self) -> None:
        self.rows = [
            _scoped_row(T_AB, WH_A, WH_B),
            _scoped_row(T_CA, WH_C, WH_A),
            _scoped_row(T_CD, WH_C, WH_D),
        ]
        self.list_calls = 0

    async def execute(self, stmt: Any, params: dict | None = None) -> MagicMock:
        sql, params = str(stmt), params or {}
        if "FROM transfer_orders to_" in sql and "ORDER BY to_.created_at" in sql:
            self.list_calls += 1
            rows = [r for r in self.rows if str(r.tenant_id) == params["tid"]]
            if "ANY(:subtree)" in sql:
                sub = set(params["subtree"])
                rows = [
                    r
                    for r in rows
                    if str(r.from_warehouse_id) in sub
                    or str(r.to_warehouse_id) in sub
                    or ("jsonb_array_elements" in sql and _names_caller(r, params))
                ]
            return MagicMock(fetchall=MagicMock(return_value=rows))
        if "WHERE to_.id = :id" in sql:
            row = next((r for r in self.rows if str(r.id) == params.get("id")), None)
            if row is not None and str(row.tenant_id) != params.get("tid"):
                row = None
            return MagicMock(fetchone=MagicMock(return_value=row))
        raise AssertionError(f"unexpected query: {sql}")

    def db(self) -> AsyncMock:
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=self.execute)
        return session


@pytest.fixture
def scoped():
    """Subtree lookups answer from _SUBTREES; line / lot / discrepancy loads are
    empty — they have their own files."""
    from services.inventory_service import InventoryService

    with (
        patch("services.transfer_discrepancies.get_descendant_node_ids", new=_descendants),
        patch.object(InventoryService, "_transfer_line_items", new=AsyncMock(return_value=[])),
        patch("services.transfer_lots.load_allocations", new=AsyncMock(return_value={})),
        patch("services.transfer_discrepancies.load_discrepancies", new=AsyncMock(return_value=[])),
    ):
        yield _World()


WM_A = _User("u-wm-a", TENANT_A, WH_A, None, "WM")
WM_E = _User("u-wm-e", TENANT_A, WH_E, None, "WM")
LM_E = _User("u-lm-e", TENANT_A, WH_E, None, "LM")
WM_NONODE = _User("u-wm-0", TENANT_A, None, None, "WM")
RT_NONODE = _User("u-rt-0", TENANT_A, None, None, "RT")
RM_REGION = _User("u-rm", TENANT_A, REGION, None, "RM")
RM_NONODE = _User("u-rm-0", TENANT_A, None, None, "RM")
TA_A = _User("u-ta-a", TENANT_A, None, None, "TA")
NM_AT_WH = _User("u-nm", TENANT_A, WH_E, None, "NM")


async def _list_ids(world: _World, user: _User) -> set[UUID]:
    from services.inventory_service import InventoryService

    return {t.transfer_id for t in await InventoryService(world.db()).list_transfers(user)}


async def _get(world: _World, user: _User, transfer_id: UUID) -> Any:
    """The transfer on success, else (status_code, detail)."""
    from services.inventory_service import InventoryService

    try:
        return await InventoryService(world.db()).get_transfer(user, transfer_id)
    except HTTPException as exc:
        return exc.status_code, exc.detail


_OUT_OF_SCOPE = (403, {"code": "TRANSFER_OUT_OF_SCOPE"})


@pytest.mark.unit
class TestTransferListScope:
    async def test_wm_sees_transfers_with_either_end_in_its_subtree(self, scoped) -> None:
        assert await _list_ids(scoped, WM_A) == {T_AB, T_CA}

    async def test_wm_outside_sees_none(self, scoped) -> None:
        assert await _list_ids(scoped, WM_E) == set()

    async def test_lm_outside_sees_none(self, scoped) -> None:
        assert await _list_ids(scoped, LM_E) == set()

    @pytest.mark.parametrize("user", [WM_NONODE, RT_NONODE], ids=["WM", "RT"])
    async def test_facility_role_without_node_gets_empty_list_and_no_query(
        self,
        scoped,
        user,
    ) -> None:
        assert await _list_ids(scoped, user) == set()
        assert scoped.list_calls == 0

    async def test_rm_sees_its_subtree(self, scoped) -> None:
        assert await _list_ids(scoped, RM_REGION) == {T_AB, T_CA}

    async def test_rm_without_node_sees_tenant(self, scoped) -> None:
        assert await _list_ids(scoped, RM_NONODE) == {T_AB, T_CA, T_CD}

    @pytest.mark.parametrize("user", [TA_A, NM_AT_WH], ids=["TA", "NM-with-node"])
    async def test_tenant_wide_roles_see_tenant(self, scoped, user) -> None:
        assert await _list_ids(scoped, user) == {T_AB, T_CA, T_CD}

    async def test_subtree_param_is_lowercased(self, scoped) -> None:
        from services.inventory_service import InventoryService

        db = scoped.db()
        await InventoryService(db).list_transfers(WM_A)
        params = db.execute.call_args_list[0].args[1]
        assert params["subtree"] == [WH_A.lower()]


@pytest.mark.unit
class TestTransferDetailScope:
    async def test_wm_gets_transfer_with_from_end_in_subtree(self, scoped) -> None:
        assert (await _get(scoped, WM_A, T_AB)).transfer_id == T_AB

    async def test_wm_gets_transfer_with_to_end_in_subtree(self, scoped) -> None:
        assert (await _get(scoped, WM_A, T_CA)).transfer_id == T_CA

    async def test_wm_outside_is_403(self, scoped) -> None:
        assert await _get(scoped, WM_A, T_CD) == _OUT_OF_SCOPE
        assert await _get(scoped, WM_E, T_AB) == _OUT_OF_SCOPE

    async def test_lm_outside_is_403(self, scoped) -> None:
        assert await _get(scoped, LM_E, T_AB) == _OUT_OF_SCOPE

    async def test_facility_role_without_node_is_403(self, scoped) -> None:
        assert await _get(scoped, WM_NONODE, T_AB) == _OUT_OF_SCOPE

    async def test_rm_outside_its_subtree_is_403(self, scoped) -> None:
        assert await _get(scoped, RM_REGION, T_CD) == _OUT_OF_SCOPE

    async def test_rm_without_node_gets_any_tenant_transfer(self, scoped) -> None:
        assert (await _get(scoped, RM_NONODE, T_CD)).transfer_id == T_CD

    async def test_ta_gets_any_tenant_transfer(self, scoped) -> None:
        assert (await _get(scoped, TA_A, T_CD)).transfer_id == T_CD

    async def test_other_tenant_is_still_404_not_403(self, scoped) -> None:
        other_wm = _User("u-wm-b", TENANT_B, WH_A, None, "WM")
        assert await _get(scoped, other_wm, T_AB) == (404, "Transfer not found")


# ── Transfer detail response fields ──────────────────────────────────────────


@pytest.mark.unit
class TestTransferDetailFields:
    async def test_detail_returns_names_and_reference_number(self, scoped) -> None:
        result = await _get(scoped, TA_A, T_CA)
        assert (result.reference_number, result.from_warehouse_name, result.to_warehouse_name) == (
            "TR-CA",
            "name-0c",
            "name-0a",
        )

    async def test_detail_created_at_is_the_row_value(self, scoped) -> None:
        assert (await _get(scoped, TA_A, T_AB)).created_at == _CREATED_AT

    async def test_detail_names_come_from_warehouses_then_organization_node(self, scoped) -> None:
        from services.inventory_service import InventoryService

        db = scoped.db()
        await InventoryService(db).get_transfer(TA_A, T_AB)
        sql = str(db.execute.call_args_list[0].args[0])
        assert "COALESCE(fw.name, fw_n.name) AS from_warehouse_name" in sql
        assert "COALESCE(tw.name, tw_n.name) AS to_warehouse_name" in sql
        assert "LEFT JOIN organization_node fw_n" in sql

    def test_new_fields_default_to_none_for_other_callers(self) -> None:
        from schemas.inventory import TransferOrderResponse

        r = TransferOrderResponse(
            transfer_id=T_AB,
            transfer_type="PULL",
            status="DRAFT",
            from_warehouse_id=UUID(WH_A),
            to_warehouse_id=UUID(WH_B),
            created_at=_CREATED_AT,
        )
        assert (r.reference_number, r.from_warehouse_name, r.to_warehouse_name) == (
            None,
            None,
            None,
        )


# ── Approvers on a transfer's approval steps keep visibility ─────────────────
#
# Approval steps can resolve TENANT_WIDE or to a fixed position, so an approver
# may sit outside both ends' subtrees. All three transfers run WH_C -> WH_D.
#   T_NODE  a step's node_id is WH_E (upper-cased: compare lowercased)
#   T_USER  a step's assigned_to_user_id is u-approver
#   T_HOLD  an ANY-mode step lists u-holder in all_holders

T_NODE = UUID("dddddddd-0000-0000-0000-00000000a001")
T_USER = UUID("dddddddd-0000-0000-0000-00000000a002")
T_HOLD = UUID("dddddddd-0000-0000-0000-00000000a003")


def _step(
    node_id: str | None = None, user_id: str | None = None, holders: tuple[str, ...] = ()
) -> dict:
    return {
        "sequence": 1,
        "position_title": "Approver",
        "position_id": None,
        "node_id": node_id,
        "assigned_to_user_id": user_id,
        "assigned_to_name": None,
        "execution_mode": "any" if holders else "sequential",
        "status": "pending",
        "all_holders": [{"user_id": u, "name": u} for u in holders],
        "holder_count": len(holders),
    }


def _approval_row(transfer_id: UUID, steps: list[dict]) -> SimpleNamespace:
    row = _scoped_row(transfer_id, WH_C, WH_D)
    row.status = "PENDING_APPROVAL"
    row.resolved_approval_steps = steps
    return row


@pytest.fixture
def approvals(scoped):
    scoped.rows += [
        _approval_row(T_NODE, [_step(node_id=WH_A), _step(node_id=WH_E.upper())]),
        _approval_row(T_USER, [_step(node_id=WH_C, user_id="U-APPROVER")]),
        _approval_row(T_HOLD, [_step(node_id=WH_D, holders=("u-other", "U-HOLDER"))]),
    ]
    return scoped


APPROVER = _User("u-approver", TENANT_A, WH_E, None, "WM")
HOLDER = _User("u-holder", TENANT_A, WH_E, None, "LM")


@pytest.mark.unit
class TestApproverTransferScope:
    async def test_approver_named_by_step_node_sees_and_gets_it(self, approvals) -> None:
        assert await _list_ids(approvals, WM_E) == {T_NODE}
        assert (await _get(approvals, WM_E, T_NODE)).transfer_id == T_NODE

    async def test_approver_named_by_assigned_to_user_id(self, approvals) -> None:
        assert T_USER in await _list_ids(approvals, APPROVER)
        assert (await _get(approvals, APPROVER, T_USER)).transfer_id == T_USER

    async def test_approver_listed_only_in_all_holders(self, approvals) -> None:
        assert T_HOLD in await _list_ids(approvals, HOLDER)
        assert (await _get(approvals, HOLDER, T_HOLD)).transfer_id == T_HOLD

    async def test_unrelated_wm_neither_sees_nor_gets_them(self, approvals) -> None:
        # WM_A: ends T_AB / T_CA only; its node WH_A sits on T_NODE's first step.
        assert await _list_ids(approvals, WM_A) == {T_AB, T_CA, T_NODE}
        for tid in (T_USER, T_HOLD, T_CD):
            assert await _get(approvals, WM_A, tid) == _OUT_OF_SCOPE
        assert await _get(approvals, LM_E, T_USER) == _OUT_OF_SCOPE
        assert await _get(approvals, LM_E, T_HOLD) == _OUT_OF_SCOPE

    async def test_null_steps_still_match_on_ends(self, approvals) -> None:
        # T_AB / T_CA have resolved_approval_steps = None.
        assert (await _get(approvals, WM_A, T_AB)).transfer_id == T_AB
        assert (await _get(approvals, WM_A, T_CA)).transfer_id == T_CA

    @pytest.mark.parametrize("steps", [None, "not json", "{}", [], ["x"], [{}]])
    def test_malformed_steps_match_nothing(self, steps) -> None:
        from services.inventory_service import _on_approval_steps

        assert _on_approval_steps({WH_E}, "u-approver", steps) is False

    def test_json_string_steps_are_parsed(self) -> None:
        import json

        from services.inventory_service import _on_approval_steps

        assert _on_approval_steps(set(), "u-approver", json.dumps([_step(user_id="u-approver")]))

    async def test_list_binds_lowercased_step_nodes_and_uid(self, approvals) -> None:
        from services.inventory_service import InventoryService

        db = approvals.db()
        await InventoryService(db).list_transfers(_User("U-WM-A", TENANT_A, WH_A, None, "WM"))
        sql, params = (
            str(db.execute.call_args_list[0].args[0]),
            db.execute.call_args_list[0].args[1],
        )
        assert "jsonb_array_elements" in sql
        assert params["step_nodes"] == [WH_A.lower()]
        assert params["uid"] == "u-wm-a"
