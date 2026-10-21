"""Review bug 8: GET /transfers/{id} returns the stored total_value and currency.

The detail page reads transfers from this endpoint, so the value must come from
the persisted row, not be left null.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

from services.inventory_service import InventoryService

TENANT = UUID("aaaaaaaa-0000-0000-0000-000000000001")
TRANSFER = UUID("cccccccc-0000-0000-0000-000000000001")
WH_A = UUID("bbbbbbbb-0000-0000-0000-00000000000a")
WH_B = UUID("bbbbbbbb-0000-0000-0000-00000000000b")


def _row(total_value: Decimal | None, currency: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        tenant_id=TENANT,
        transfer_type="PULL",
        status="DRAFT",
        reference_number="TR-0001",
        from_warehouse_id=WH_A,
        from_warehouse_name="Source",
        to_warehouse_id=WH_B,
        to_warehouse_name="Destination",
        created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        is_self_approved=False,
        resolved_approval_steps=None,
        current_approval_step=None,
        transfer_type_config_id=None,
        total_value=total_value,
        currency=currency,
    )


async def _get(row: SimpleNamespace):
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(fetchone=MagicMock(return_value=row)))
    user = SimpleNamespace(tenant_id=TENANT, user_id="u-wm")
    svc = InventoryService(db)
    with (
        patch.object(svc, "_transfer_scope", AsyncMock(return_value=None)),
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
        return await svc.get_transfer(user, TRANSFER)


class TestTransferDetailTotals:
    async def test_stored_value_and_currency_are_returned(self) -> None:
        result = await _get(_row(Decimal("5000"), "ETB"))
        assert result.total_value == Decimal("5000")
        assert result.currency == "ETB"

    async def test_unpriced_transfer_keeps_null_value(self) -> None:
        result = await _get(_row(None, "ETB"))
        assert result.total_value is None
        assert result.currency == "ETB"
