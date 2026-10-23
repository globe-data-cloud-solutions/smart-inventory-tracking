"""RB-8 bug 8: transfer mutation responses carry the full transfer shape.

A mutation (create, submit, approve, dispatch, receive, PATCH) must answer with the
same shape GET returns: lines, lot allocations, discrepancies, approval state and
totals, read back from the row the write just committed. The mutation has already
passed its own permission and scope checks, so the read-back does not repeat the
GET scope check.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from fastapi import HTTPException

from services.inventory_service import InventoryService

TENANT = UUID("aaaaaaaa-0000-0000-0000-000000000001")
TRANSFER = UUID("cccccccc-0000-0000-0000-000000000001")
WH_A = UUID("bbbbbbbb-0000-0000-0000-00000000000a")
WH_B = UUID("bbbbbbbb-0000-0000-0000-00000000000b")


def _row() -> SimpleNamespace:
    return SimpleNamespace(
        tenant_id=TENANT,
        transfer_type="PULL",
        status="APPROVED",
        reference_number="TR-0002",
        from_warehouse_id=WH_A,
        from_warehouse_name="Source",
        to_warehouse_id=WH_B,
        to_warehouse_name="Destination",
        created_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
        is_self_approved=False,
        resolved_approval_steps=[{"step": 1}],
        current_approval_step=2,
        transfer_type_config_id=None,
        total_value=Decimal("1250.00"),
        currency="ETB",
    )


def _user() -> SimpleNamespace:
    return SimpleNamespace(tenant_id=TENANT, user_id="u-wm")


@pytest.mark.asyncio
async def test_read_after_write_returns_lines_and_totals_from_reread_row() -> None:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(fetchone=MagicMock(return_value=_row())))
    svc = InventoryService(db)

    line_items = AsyncMock(return_value=[])
    with (
        patch.object(svc, "_transfer_line_items", line_items),
        patch(
            "services.inventory_service.transfer_lots.load_allocations",
            AsyncMock(return_value={}),
        ),
        patch(
            "services.inventory_service.transfer_discrepancies.load_discrepancies",
            AsyncMock(return_value=[]),
        ),
    ):
        out = await svc.read_transfer_after_write(_user(), TRANSFER)

    assert out.transfer_id == TRANSFER
    assert out.status == "APPROVED"
    assert out.total_value == Decimal("1250.00")
    assert out.currency == "ETB"
    assert out.current_approval_step == 2
    assert out.resolved_approval_steps == [{"step": 1}]
    line_items.assert_awaited_once_with(TRANSFER)


@pytest.mark.asyncio
async def test_read_after_write_skips_the_get_scope_check() -> None:
    """A sender who is outside the transfer's scope must still see the transfer it just wrote."""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(fetchone=MagicMock(return_value=_row())))
    svc = InventoryService(db)
    scope_check = AsyncMock(side_effect=AssertionError("scope must not be checked"))

    with (
        patch.object(svc, "_transfer_scope", scope_check),
        patch.object(svc, "_transfer_line_items", AsyncMock(return_value=[])),
        patch(
            "services.inventory_service.transfer_lots.load_allocations",
            AsyncMock(return_value={}),
        ),
        patch(
            "services.inventory_service.transfer_discrepancies.load_discrepancies",
            AsyncMock(return_value=[]),
        ),
    ):
        out = await svc.read_transfer_after_write(_user(), TRANSFER)

    scope_check.assert_not_awaited()
    assert out.transfer_id == TRANSFER


@pytest.mark.asyncio
async def test_read_after_write_404s_when_row_is_missing() -> None:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(fetchone=MagicMock(return_value=None)))
    svc = InventoryService(db)

    with pytest.raises(HTTPException) as exc:
        await svc.read_transfer_after_write(_user(), TRANSFER)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_patch_received_responds_with_the_read_back_shape() -> None:
    """The PATCH handler returns what read_transfer_after_write produced, not the
    service's own return value."""
    from routers.transfer import transition_transfer
    from schemas.inventory import TransferTransitionRequest
    from shared.permissions.middleware import PermissionResult

    readback = MagicMock(name="readback")
    wm_user = SimpleNamespace(tenant_id=TENANT, user_id="u-wm", role="WM", role_code="WM")

    with (
        patch(
            "shared.permissions.middleware.check_permission",
            AsyncMock(return_value=PermissionResult(allowed=True)),
        ),
        patch(
            "shared.billing.contract_stage.get_tenant_contract_stage",
            AsyncMock(
                return_value={"stage": "ACTIVE", "contract_end": None, "read_only_since": None}
            ),
        ),
        patch("routers.transfer.InventoryService") as svc_cls,
    ):
        svc_cls.return_value.receive_transfer = AsyncMock(return_value=MagicMock())
        svc_cls.return_value.read_transfer_after_write = AsyncMock(return_value=readback)
        resp = await transition_transfer(
            transfer_id=TRANSFER,
            body=TransferTransitionRequest(next_status="RECEIVED"),
            user=wm_user,
            db=AsyncMock(),
        )

    svc_cls.return_value.read_transfer_after_write.assert_awaited_once_with(wm_user, TRANSFER)
    assert resp.data is readback
