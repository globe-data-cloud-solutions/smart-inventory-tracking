"""Unit tests for list_transfers() and list_adjustments() role-scoped filtering.

Tests verify:
1. WM role: SQL contains warehouse_id filter restricting results to their facility.
2. NM/TA role: SQL does NOT contain warehouse_id filter — sees all tenant transfers.
3. Response shape is correct for both endpoints.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

_NOW = datetime(2026, 5, 24, 10, 0, 0, tzinfo=timezone.utc)

from services.inventory_service import InventoryService


TENANT_ID    = "10000000-0000-0000-0000-000000000001"
WAREHOUSE_A  = "20000000-0000-0000-0000-000000000001"
WAREHOUSE_B  = "20000000-0000-0000-0000-000000000002"
PRODUCT_ID   = "aaaaaaaa-0000-0000-0000-000000000001"
TRANSFER_ID  = "cccccccc-0000-0000-0000-000000000001"
ADJ_ID       = "dddddddd-0000-0000-0000-000000000001"


@dataclass
class _User:
    user_id: str
    tenant_id: str
    warehouse_id: str | None
    region_id: str | None
    role: str


WM_USER = _User("u-wm", TENANT_ID, WAREHOUSE_A, None, "WM")
NM_USER = _User("u-nm", TENANT_ID, None,        None, "NM")
TA_USER = _User("u-ta", TENANT_ID, None,        None, "TA")


def _make_transfer_row() -> MagicMock:
    row = MagicMock()
    row.transfer_id          = UUID(TRANSFER_ID)
    row.transfer_type        = "PULL"
    row.status               = "DRAFT"
    row.from_warehouse_id    = UUID(WAREHOUSE_A)
    row.from_warehouse_name  = "AW North"
    row.to_warehouse_id      = UUID(WAREHOUSE_B)
    row.to_warehouse_name    = "AW Main"
    row.created_by           = "u-wm"
    row.created_at           = _NOW
    row.updated_at           = None
    return row


def _make_line_row() -> MagicMock:
    row = MagicMock()
    row.product_id    = UUID(PRODUCT_ID)
    row.product_name  = "Cement 50kg"
    row.sku           = "CEM-50"
    row.quantity      = Decimal("100")
    row.uom           = "bags"
    return row


def _make_adj_row() -> MagicMock:
    row = MagicMock()
    row.adjustment_id  = UUID(ADJ_ID)
    row.product_id     = UUID(PRODUCT_ID)
    row.product_name   = "Cement 50kg"
    row.sku            = "CEM-50"
    row.warehouse_id   = UUID(WAREHOUSE_A)
    row.warehouse_name = "AW North"
    row.quantity_delta = Decimal("-20")
    row.reason_code    = "DAMAGE"
    row.status         = "DRAFT"
    row.created_by     = "u-wm"
    row.created_at     = _NOW
    row.notes          = None
    return row


@pytest.mark.unit
class TestListTransfersScopedByRole:

    async def test_wm_list_includes_warehouse_filter_in_params(self) -> None:
        """list_transfers() for a WM must pass their warehouse_id into the SQL params.

        The wh_filter clause restricts results to transfers where
        from_warehouse_id = :wid OR to_warehouse_id = :wid.
        """
        session = AsyncMock()
        # First execute: transfer rows; second execute (per transfer): line rows
        session.execute = AsyncMock(side_effect=[
            MagicMock(fetchall=MagicMock(return_value=[_make_transfer_row()])),
            MagicMock(fetchall=MagicMock(return_value=[_make_line_row()])),
        ])

        svc = InventoryService(session)
        results = await svc.list_transfers(WM_USER)

        # Verify the first execute (list query) received warehouse_id in params
        list_call = session.execute.call_args_list[0]
        params = list_call.args[1] if len(list_call.args) > 1 else list_call.kwargs.get("params", {})
        assert "wid" in params, (
            "WM list_transfers must include 'wid' (warehouse_id) in SQL params"
        )
        assert params["wid"] == WAREHOUSE_A

        # SQL text must contain the warehouse filter clause
        sql_text = str(list_call.args[0])
        assert "from_warehouse_id" in sql_text or "to_warehouse_id" in sql_text, (
            "WM query must filter by from_warehouse_id or to_warehouse_id"
        )

    async def test_nm_list_does_not_filter_by_warehouse(self) -> None:
        """list_transfers() for NM must NOT include warehouse_id in SQL params.

        NM sees all transfers for the tenant regardless of warehouse assignment.
        """
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            MagicMock(fetchall=MagicMock(return_value=[_make_transfer_row()])),
            MagicMock(fetchall=MagicMock(return_value=[_make_line_row()])),
        ])

        svc = InventoryService(session)
        await svc.list_transfers(NM_USER)

        list_call = session.execute.call_args_list[0]
        params = list_call.args[1] if len(list_call.args) > 1 else {}
        assert "wid" not in params, (
            "NM list_transfers must NOT include 'wid' — NM sees all tenant transfers"
        )

    async def test_ta_list_does_not_filter_by_warehouse(self) -> None:
        """Tenant Admin (TA) sees all transfers for the tenant."""
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            MagicMock(fetchall=MagicMock(return_value=[])),
        ])

        svc = InventoryService(session)
        results = await svc.list_transfers(TA_USER)

        list_call = session.execute.call_args_list[0]
        params = list_call.args[1] if len(list_call.args) > 1 else {}
        assert "wid" not in params

    async def test_list_transfers_returns_enriched_shape(self) -> None:
        """list_transfers() returns TransferListItem with warehouse names and lines."""
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            MagicMock(fetchall=MagicMock(return_value=[_make_transfer_row()])),
            MagicMock(fetchall=MagicMock(return_value=[_make_line_row()])),
        ])

        svc = InventoryService(session)
        results = await svc.list_transfers(NM_USER)

        assert len(results) == 1
        item = results[0]
        assert item.transfer_id        == UUID(TRANSFER_ID)
        assert item.transfer_type      == "PULL"
        assert item.status             == "DRAFT"
        assert item.from_warehouse_name == "AW North"
        assert item.to_warehouse_name   == "AW Main"
        assert len(item.lines)          == 1
        assert item.lines[0].product_name == "Cement 50kg"
        assert item.lines[0].sku          == "CEM-50"
        assert item.lines[0].quantity     == Decimal("100")

    async def test_list_transfers_empty_returns_empty_list(self) -> None:
        """Empty transfer_orders table returns an empty list, not an error."""
        session = AsyncMock()
        session.execute = AsyncMock(
            return_value=MagicMock(fetchall=MagicMock(return_value=[]))
        )

        svc = InventoryService(session)
        results = await svc.list_transfers(NM_USER)

        assert results == []

    async def test_list_transfers_pagination_offset(self) -> None:
        """page=2 with limit=10 must set OFFSET=10 in params."""
        session = AsyncMock()
        session.execute = AsyncMock(
            return_value=MagicMock(fetchall=MagicMock(return_value=[]))
        )

        svc = InventoryService(session)
        await svc.list_transfers(NM_USER, page=2, limit=10)

        list_call = session.execute.call_args_list[0]
        params = list_call.args[1] if len(list_call.args) > 1 else {}
        assert params["offset"] == 10, f"Expected offset=10 for page=2 limit=10, got {params.get('offset')}"
        assert params["limit"]  == 10


@pytest.mark.unit
class TestListAdjustmentsScopedByRole:

    async def test_wm_list_includes_warehouse_filter_in_params(self) -> None:
        """list_adjustments() for WM must pass warehouse_id into SQL params."""
        session = AsyncMock()
        session.execute = AsyncMock(
            return_value=MagicMock(fetchall=MagicMock(return_value=[_make_adj_row()]))
        )

        svc = InventoryService(session)
        await svc.list_adjustments(WM_USER)

        list_call = session.execute.call_args_list[0]
        params = list_call.args[1] if len(list_call.args) > 1 else {}
        assert "wid" in params, (
            "WM list_adjustments must include 'wid' in SQL params"
        )
        assert params["wid"] == WAREHOUSE_A

    async def test_nm_list_does_not_filter_by_warehouse(self) -> None:
        """NM list_adjustments must NOT include warehouse_id filter."""
        session = AsyncMock()
        session.execute = AsyncMock(
            return_value=MagicMock(fetchall=MagicMock(return_value=[]))
        )

        svc = InventoryService(session)
        await svc.list_adjustments(NM_USER)

        list_call = session.execute.call_args_list[0]
        params = list_call.args[1] if len(list_call.args) > 1 else {}
        assert "wid" not in params

    async def test_list_adjustments_returns_correct_shape(self) -> None:
        """list_adjustments() returns AdjustmentListItem with product/warehouse names."""
        session = AsyncMock()
        session.execute = AsyncMock(
            return_value=MagicMock(fetchall=MagicMock(return_value=[_make_adj_row()]))
        )

        svc = InventoryService(session)
        results = await svc.list_adjustments(NM_USER)

        assert len(results) == 1
        item = results[0]
        assert item.adjustment_id  == UUID(ADJ_ID)
        assert item.product_name   == "Cement 50kg"
        assert item.sku            == "CEM-50"
        assert item.warehouse_name == "AW North"
        assert item.quantity_delta == Decimal("-20")
        assert item.reason_code    == "DAMAGE"
        assert item.status         == "DRAFT"


@pytest.mark.unit
class TestIssueStockBelowZeroBlocked:

    async def test_issue_below_zero_blocked_by_record_transaction(self) -> None:
        """record_transaction() raises when stock would go below zero.

        issue_stock() does not swallow the exception — it propagates to the caller
        which maps it to HTTP 422 (INSUFFICIENT_STOCK). The service layer must not
        silently succeed when the ledger rejects the transaction.
        """
        from schemas.inventory import IssueStockRequest

        body = IssueStockRequest(
            product_id=UUID(PRODUCT_ID),
            warehouse_id=UUID(WAREHOUSE_A),
            quantity=Decimal("9999"),
            reason_code="SALE",
            idempotency_key="issue:zero-floor:001",
        )

        insufficient_stock_error = Exception("INSUFFICIENT_STOCK: balance would go below 0")

        session = AsyncMock()
        svc = InventoryService(session)

        with patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock,
            side_effect=insufficient_stock_error,
        ):
            with pytest.raises(Exception, match="INSUFFICIENT_STOCK"):
                await svc.issue_stock(WM_USER, body)
