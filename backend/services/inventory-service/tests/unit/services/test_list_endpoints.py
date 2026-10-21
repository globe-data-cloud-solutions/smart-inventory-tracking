"""Unit tests for list_transfers() and list_adjustments() role-scoped filtering.

Tests verify:
1. WM role: SQL contains a node-subtree filter restricting results to their facility.
2. NM/TA role: SQL does NOT contain warehouse_id filter — sees all tenant transfers.
3. Response shape is correct for both endpoints.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from services.inventory_service import InventoryService

_NOW = datetime(2026, 5, 24, 10, 0, 0, tzinfo=timezone.utc)


TENANT_ID = "10000000-0000-0000-0000-000000000001"
WAREHOUSE_A = "20000000-0000-0000-0000-000000000001"
WAREHOUSE_B = "20000000-0000-0000-0000-000000000002"
PRODUCT_ID = "aaaaaaaa-0000-0000-0000-000000000001"
TRANSFER_ID = "cccccccc-0000-0000-0000-000000000001"
LINE_ID = "eeeeeeee-0000-0000-0000-000000000001"
ADJ_ID = "dddddddd-0000-0000-0000-000000000001"


@dataclass
class _User:
    user_id: str
    tenant_id: str
    warehouse_id: str | None
    region_id: str | None
    role: str


WM_USER = _User("u-wm", TENANT_ID, WAREHOUSE_A, None, "WM")
NM_USER = _User("u-nm", TENANT_ID, None, None, "NM")
TA_USER = _User("u-ta", TENANT_ID, None, None, "TA")


def _make_transfer_row() -> MagicMock:
    row = MagicMock()
    row.transfer_id = UUID(TRANSFER_ID)
    row.transfer_type = "PULL"
    row.status = "DRAFT"
    row.from_warehouse_id = UUID(WAREHOUSE_A)
    row.from_warehouse_name = "AW North"
    row.to_warehouse_id = UUID(WAREHOUSE_B)
    row.to_warehouse_name = "AW Main"
    row.created_by = "u-wm"
    row.created_at = _NOW
    row.updated_at = None
    return row


def _make_line_row() -> MagicMock:
    row = MagicMock()
    row.line_id = UUID(LINE_ID)
    row.product_id = UUID(PRODUCT_ID)
    row.product_name = "Cement 50kg"
    row.sku = "CEM-50"
    row.quantity = Decimal("100")
    row.uom = "bags"
    return row


def _make_adj_row() -> MagicMock:
    row = MagicMock()
    row.adjustment_id = UUID(ADJ_ID)
    row.product_id = UUID(PRODUCT_ID)
    row.product_name = "Cement 50kg"
    row.sku = "CEM-50"
    row.warehouse_id = UUID(WAREHOUSE_A)
    row.warehouse_name = "AW North"
    row.quantity_delta = Decimal("-20")
    row.reason_code = "DAMAGE"
    row.status = "DRAFT"
    row.created_by = "u-wm"
    row.created_at = _NOW
    row.notes = None
    row.lot_id = None
    row.lot_number = None
    row.expiry_date = None
    row.auto_lot = False
    return row


@pytest.mark.unit
class TestListTransfersScopedByRole:
    async def test_wm_list_includes_warehouse_filter_in_params(self) -> None:
        """list_transfers() for a WM must pass its node subtree into the SQL params.

        The wh_filter clause restricts results to transfers where
        from_warehouse_id = ANY(:subtree) OR to_warehouse_id = ANY(:subtree)
        (RB-2 — subtree via get_descendant_node_ids, not a raw equality).
        """
        session = AsyncMock()
        # First execute: transfer rows; second execute (per transfer): line rows
        session.execute = AsyncMock(
            side_effect=[
                MagicMock(fetchall=MagicMock(return_value=[_make_transfer_row()])),
                MagicMock(fetchall=MagicMock(return_value=[_make_line_row()])),
            ]
        )

        svc = InventoryService(session)
        with patch(
            "services.transfer_discrepancies.get_descendant_node_ids",
            new=AsyncMock(return_value={WAREHOUSE_A}),
        ):
            await svc.list_transfers(WM_USER)

        # Verify the first execute (list query) received the subtree in params
        list_call = session.execute.call_args_list[0]
        params = (
            list_call.args[1] if len(list_call.args) > 1 else list_call.kwargs.get("params", {})
        )
        assert "subtree" in params, (
            "WM list_transfers must include 'subtree' (node subtree) in SQL params"
        )
        assert params["subtree"] == [WAREHOUSE_A]

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
        session.execute = AsyncMock(
            side_effect=[
                MagicMock(fetchall=MagicMock(return_value=[_make_transfer_row()])),
                MagicMock(fetchall=MagicMock(return_value=[_make_line_row()])),
            ]
        )

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
        session.execute = AsyncMock(
            side_effect=[
                MagicMock(fetchall=MagicMock(return_value=[])),
            ]
        )

        svc = InventoryService(session)
        await svc.list_transfers(TA_USER)

        list_call = session.execute.call_args_list[0]
        params = list_call.args[1] if len(list_call.args) > 1 else {}
        assert "wid" not in params

    async def test_list_transfers_returns_enriched_shape(self) -> None:
        """list_transfers() returns TransferListItem with warehouse names and lines."""
        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                MagicMock(fetchall=MagicMock(return_value=[_make_transfer_row()])),
                MagicMock(fetchall=MagicMock(return_value=[_make_line_row()])),
            ]
        )

        svc = InventoryService(session)
        results = await svc.list_transfers(NM_USER)

        assert len(results) == 1
        item = results[0]
        assert item.transfer_id == UUID(TRANSFER_ID)
        assert item.transfer_type == "PULL"
        assert item.status == "DRAFT"
        assert item.from_warehouse_name == "AW North"
        assert item.to_warehouse_name == "AW Main"
        assert len(item.lines) == 1
        assert item.lines[0].product_name == "Cement 50kg"
        assert item.lines[0].sku == "CEM-50"
        assert item.lines[0].quantity == Decimal("100")

    async def test_list_transfers_lines_carry_line_id(self) -> None:
        """Every line of a list item carries its transfer_order_lines id — the
        receive form sends it back as line_id."""
        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                MagicMock(fetchall=MagicMock(return_value=[_make_transfer_row()])),
                MagicMock(fetchall=MagicMock(return_value=[_make_line_row()])),
            ]
        )

        svc = InventoryService(session)
        results = await svc.list_transfers(NM_USER)

        assert [line.line_id for line in results[0].lines] == [UUID(LINE_ID)]
        lines_sql = str(session.execute.call_args_list[1].args[0])
        assert "tol.id" in lines_sql and "AS line_id" in lines_sql

    async def test_list_transfers_empty_returns_empty_list(self) -> None:
        """Empty transfer_orders table returns an empty list, not an error."""
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(fetchall=MagicMock(return_value=[])))

        svc = InventoryService(session)
        results = await svc.list_transfers(NM_USER)

        assert results == []

    async def test_list_transfers_pagination_offset(self) -> None:
        """page=2 with limit=10 must set OFFSET=10 in params."""
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(fetchall=MagicMock(return_value=[])))

        svc = InventoryService(session)
        await svc.list_transfers(NM_USER, page=2, limit=10)

        list_call = session.execute.call_args_list[0]
        params = list_call.args[1] if len(list_call.args) > 1 else {}
        assert params["offset"] == 10, (
            f"Expected offset=10 for page=2 limit=10, got {params.get('offset')}"
        )
        assert params["limit"] == 10

    async def test_list_transfers_returns_actual_transfer_type(self) -> None:
        """list_transfers() must return the DB transfer_type, not hardcoded 'PULL'.

        Regression: the SQL previously had 'PULL' AS transfer_type which meant
        every PUSH and SISTER transfer appeared as PULL in the frontend, causing
        HTTP 422 on the first action attempt because the wrong state machine was
        consulted. The SQL must select to_.transfer_type from the table.
        """
        push_row = _make_transfer_row()
        push_row.transfer_type = "PUSH"

        sister_row = _make_transfer_row()
        sister_row.transfer_type = "SISTER"

        for expected_type, db_row in [("PUSH", push_row), ("SISTER", sister_row)]:
            session = AsyncMock()
            session.execute = AsyncMock(
                side_effect=[
                    MagicMock(fetchall=MagicMock(return_value=[db_row])),
                    MagicMock(fetchall=MagicMock(return_value=[])),
                ]
            )

            svc = InventoryService(session)
            results = await svc.list_transfers(NM_USER)

            assert len(results) == 1
            assert results[0].transfer_type == expected_type, (
                f"Expected transfer_type={expected_type!r} from DB row, "
                f"got {results[0].transfer_type!r}. "
                "Hardcoded 'PULL' in list_transfers SQL was the root cause of "
                "HTTP 422 on first action attempt for PUSH/SISTER transfers."
            )


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
        assert "wid" in params, "WM list_adjustments must include 'wid' in SQL params"
        assert params["wid"] == WAREHOUSE_A

    async def test_nm_list_does_not_filter_by_warehouse(self) -> None:
        """NM list_adjustments must NOT include warehouse_id filter."""
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(fetchall=MagicMock(return_value=[])))

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
        assert item.adjustment_id == UUID(ADJ_ID)
        assert item.product_name == "Cement 50kg"
        assert item.sku == "CEM-50"
        assert item.warehouse_name == "AW North"
        assert item.quantity_delta == Decimal("-20")
        assert item.reason_code == "DAMAGE"
        assert item.status == "DRAFT"


@pytest.mark.unit
class TestFactorySpecificProductValidation:
    """create_transfer() must reject lines where from_warehouse_id is outside
    the product's source_factory subtree. Standard products (source_factory_id IS NULL)
    are always allowed from any warehouse.
    """

    FACTORY_ID = "ffffffff-0000-0000-0000-000000000001"
    SUBTREE_WH = "20000000-0000-0000-0000-000000000001"  # inside factory subtree
    OUTSIDE_WH = "20000000-0000-0000-0000-000000000099"  # NOT in subtree
    PRODUCT_B = "bbbbbbbb-0000-0000-0000-000000000001"

    def _make_user(self, wh_id: str) -> _User:
        return _User("u-wm", TENANT_ID, wh_id, None, "WM")

    def _make_transfer_body(self, from_wh: str, product_id: str) -> Any:
        from schemas.inventory import TransferOrderRequest, TransferLineRequest

        return TransferOrderRequest(
            from_warehouse_id=UUID(from_wh),
            to_warehouse_id=UUID(WAREHOUSE_B),
            transfer_type="PULL",
            lines=[TransferLineRequest(product_id=UUID(product_id), quantity=Decimal("10"))],
        )

    async def test_standard_product_any_source_allowed(self) -> None:
        """Product with source_factory_id=NULL may be transferred from any warehouse."""
        product_row = MagicMock()
        product_row.source_factory_id = None
        product_row.sku = "STD-001"

        oh_row = MagicMock()
        oh_row.qty = Decimal("9999")
        pend_row = MagicMock()
        pend_row.pending = Decimal("0")

        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                MagicMock(
                    fetchone=MagicMock(return_value=MagicMock(is_active=True))
                ),  # from warehouse active check
                MagicMock(
                    fetchone=MagicMock(return_value=MagicMock(is_active=True))
                ),  # to warehouse active check
                MagicMock(fetchone=MagicMock(return_value=product_row)),  # products lookup
                MagicMock(fetchone=MagicMock(return_value=None)),  # config lookup → None
                MagicMock(fetchone=MagicMock(return_value=oh_row)),  # on_hand (stock check)
                MagicMock(fetchone=MagicMock(return_value=pend_row)),  # pending_out (stock check)
                MagicMock(fetchone=MagicMock(return_value=None)),  # unit_price → None
                MagicMock(),  # INSERT transfer_orders
                MagicMock(),  # INSERT transfer_order_lines
            ]
        )

        svc = InventoryService(session)
        user = self._make_user(self.OUTSIDE_WH)
        body = self._make_transfer_body(self.OUTSIDE_WH, PRODUCT_ID)

        with patch("services.inventory_service.record_transaction", new_callable=AsyncMock):
            result = await svc.create_transfer(user, body)

        assert result.status == "DRAFT"

    async def test_factory_product_valid_source_accepted(self) -> None:
        """Product with source_factory_id set, from_warehouse_id IS in subtree → allowed."""
        product_row = MagicMock()
        product_row.source_factory_id = self.FACTORY_ID
        product_row.sku = "FAC-001"

        subtree_result = MagicMock()
        subtree_result.fetchall = MagicMock(return_value=[(self.FACTORY_ID,), (self.SUBTREE_WH,)])

        oh_row2 = MagicMock()
        oh_row2.qty = Decimal("9999")
        pend_row2 = MagicMock()
        pend_row2.pending = Decimal("0")

        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                MagicMock(
                    fetchone=MagicMock(return_value=MagicMock(is_active=True))
                ),  # from warehouse active check
                MagicMock(
                    fetchone=MagicMock(return_value=MagicMock(is_active=True))
                ),  # to warehouse active check
                MagicMock(fetchone=MagicMock(return_value=product_row)),  # products lookup
                subtree_result,  # subtree CTE
                MagicMock(fetchone=MagicMock(return_value=None)),  # config lookup → None
                MagicMock(fetchone=MagicMock(return_value=oh_row2)),  # on_hand (stock check)
                MagicMock(fetchone=MagicMock(return_value=pend_row2)),  # pending_out (stock check)
                MagicMock(fetchone=MagicMock(return_value=None)),  # unit_price → None
                MagicMock(),  # INSERT transfer_orders
                MagicMock(),  # INSERT lines
            ]
        )

        svc = InventoryService(session)
        user = self._make_user(self.SUBTREE_WH)
        body = self._make_transfer_body(self.SUBTREE_WH, self.PRODUCT_B)

        result = await svc.create_transfer(user, body)

        assert result.status == "DRAFT"

    async def test_factory_product_invalid_source_raises_422(self) -> None:
        """Product with source_factory_id set, from_warehouse_id NOT in subtree → HTTP 422."""
        from fastapi import HTTPException

        product_row = MagicMock()
        product_row.source_factory_id = self.FACTORY_ID
        product_row.sku = "FAC-001"

        subtree_result = MagicMock()
        subtree_result.fetchall = MagicMock(return_value=[(self.FACTORY_ID,), (self.SUBTREE_WH,)])

        factory_node_row = MagicMock()
        factory_node_row.name = "Jimma Factory"

        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                MagicMock(
                    fetchone=MagicMock(return_value=MagicMock(is_active=True))
                ),  # from warehouse active check
                MagicMock(
                    fetchone=MagicMock(return_value=MagicMock(is_active=True))
                ),  # to warehouse active check
                MagicMock(fetchone=MagicMock(return_value=product_row)),  # products lookup
                subtree_result,  # subtree CTE
                MagicMock(fetchone=MagicMock(return_value=factory_node_row)),  # factory name lookup
            ]
        )

        svc = InventoryService(session)
        user = self._make_user(self.OUTSIDE_WH)
        body = self._make_transfer_body(self.OUTSIDE_WH, self.PRODUCT_B)

        with pytest.raises(HTTPException) as exc_info:
            await svc.create_transfer(user, body)

        assert exc_info.value.status_code == 422
        detail = exc_info.value.detail
        assert detail["code"] == "INVALID_SOURCE_FACTORY"
        assert "FAC-001" in detail["message"]
        assert "Jimma Factory" in detail["message"]

    async def test_factory_product_invalid_source_error_message_format(self) -> None:
        """Error message must contain SKU and factory name in the expected format."""
        from fastapi import HTTPException

        product_row = MagicMock()
        product_row.source_factory_id = self.FACTORY_ID
        product_row.sku = "CEM-50KG"

        subtree_result = MagicMock()
        subtree_result.fetchall = MagicMock(return_value=[(self.FACTORY_ID,)])

        factory_node_row = MagicMock()
        factory_node_row.name = "Addis Main Factory"

        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                MagicMock(
                    fetchone=MagicMock(return_value=MagicMock(is_active=True))
                ),  # from warehouse active check
                MagicMock(
                    fetchone=MagicMock(return_value=MagicMock(is_active=True))
                ),  # to warehouse active check
                MagicMock(fetchone=MagicMock(return_value=product_row)),
                subtree_result,
                MagicMock(fetchone=MagicMock(return_value=factory_node_row)),
            ]
        )

        svc = InventoryService(session)
        user = self._make_user(self.OUTSIDE_WH)
        body = self._make_transfer_body(self.OUTSIDE_WH, self.PRODUCT_B)

        with pytest.raises(HTTPException) as exc_info:
            await svc.create_transfer(user, body)

        msg = exc_info.value.detail["message"]
        assert msg == "Product CEM-50KG can only be sourced from Addis Main Factory"

    async def test_multiple_lines_first_invalid_raises_immediately(self) -> None:
        """Validation short-circuits on the first invalid line — no partial insert."""
        from fastapi import HTTPException

        bad_product = MagicMock()
        bad_product.source_factory_id = self.FACTORY_ID
        bad_product.sku = "BAD-SKU"

        subtree_result = MagicMock()
        subtree_result.fetchall = MagicMock(return_value=[(self.FACTORY_ID,)])

        factory_node_row = MagicMock()
        factory_node_row.name = "Locked Factory"

        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                MagicMock(
                    fetchone=MagicMock(return_value=MagicMock(is_active=True))
                ),  # from warehouse active check
                MagicMock(
                    fetchone=MagicMock(return_value=MagicMock(is_active=True))
                ),  # to warehouse active check
                MagicMock(fetchone=MagicMock(return_value=bad_product)),
                subtree_result,
                MagicMock(fetchone=MagicMock(return_value=factory_node_row)),
            ]
        )

        svc = InventoryService(session)
        user = self._make_user(self.OUTSIDE_WH)

        from schemas.inventory import TransferOrderRequest, TransferLineRequest

        body = TransferOrderRequest(
            from_warehouse_id=UUID(self.OUTSIDE_WH),
            to_warehouse_id=UUID(WAREHOUSE_B),
            transfer_type="PULL",
            lines=[
                TransferLineRequest(product_id=UUID(self.PRODUCT_B), quantity=Decimal("5")),
                TransferLineRequest(product_id=UUID(PRODUCT_ID), quantity=Decimal("3")),
            ],
        )

        with pytest.raises(HTTPException) as exc_info:
            await svc.create_transfer(user, body)

        assert exc_info.value.status_code == 422
        # No INSERT should have been attempted — execute call count = 5
        # (from-active + to-active checks, product, subtree, factory name)
        assert session.execute.call_count == 5


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

        from services.dispatch_service import ProductDispatchInfo

        # issue_stock() loads the product first — a non-batch product here.
        with (
            patch(
                "services.inventory_service.load_product",
                new_callable=AsyncMock,
                return_value=ProductDispatchInfo(
                    batch_tracking=False, expiry_tracking=False, dispatch_strategy=None
                ),
            ),
            patch(
                "services.inventory_service.record_transaction",
                new_callable=AsyncMock,
                side_effect=insufficient_stock_error,
            ),
        ):
            with pytest.raises(Exception, match="INSUFFICIENT_STOCK"):
                await svc.issue_stock(WM_USER, body)


@pytest.mark.unit
class TestTransferRequestsEnrich:
    """Regression tests for GAP 2: _enrich in transfer_requests.py queried only
    the warehouses table. Fix: COALESCE falls back to organization_node so that
    org-node-based facilities (created via Org Setup) resolve to their display name.
    """

    async def test_enrich_uses_org_node_name_when_no_warehouses_row(self) -> None:
        """_enrich returns the organization_node name when warehouses has no matching row.

        The COALESCE query returns the first non-NULL of:
          (SELECT name FROM warehouses WHERE id = :id)
          (SELECT name FROM organization_node WHERE id = :id)
        When warehouses returns NULL, the org node name must be used.
        """
        from routers.transfer_requests import _enrich

        row = MagicMock()
        row.id = uuid.uuid4()
        row.tenant_id = UUID(TENANT_ID)
        row.requesting_warehouse_id = UUID(WAREHOUSE_A)
        row.source_warehouse_id = UUID(WAREHOUSE_B)
        row.product_id = UUID(PRODUCT_ID)
        row.quantity = Decimal("100")
        row.required_date = None
        row.notes = None
        row.status = "PENDING"
        row.created_at = datetime(2026, 5, 28, 10, 0, 0, tzinfo=timezone.utc)

        req_wh_row = MagicMock()
        req_wh_row.name = "North Org Node"
        src_wh_row = MagicMock()
        src_wh_row.name = "South Org Node"
        product_row = MagicMock()
        product_row.name = "Cement 50kg"
        product_row.sku = "CEM-50"

        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                MagicMock(
                    fetchone=MagicMock(return_value=req_wh_row)
                ),  # COALESCE for requesting_wh
                MagicMock(fetchone=MagicMock(return_value=src_wh_row)),  # COALESCE for source_wh
                MagicMock(fetchone=MagicMock(return_value=product_row)),  # product lookup
            ]
        )

        result = await _enrich(row, session)

        assert result.requesting_warehouse_name == "North Org Node", (
            "_enrich must fall back to organization_node name when no warehouses row exists"
        )
        assert result.source_warehouse_name == "South Org Node"
        assert result.product_name == "Cement 50kg"
        assert result.product_sku == "CEM-50"

    async def test_enrich_coalesce_query_contains_org_node(self) -> None:
        """_enrich's warehouse lookup SQL must reference organization_node.

        Verifies that the COALESCE fix is actually present in the SQL sent to the
        database — not just that the result happens to be correct.
        """
        from routers.transfer_requests import _enrich

        row = MagicMock()
        row.id = uuid.uuid4()
        row.tenant_id = UUID(TENANT_ID)
        row.requesting_warehouse_id = UUID(WAREHOUSE_A)
        row.source_warehouse_id = UUID(WAREHOUSE_B)
        row.product_id = UUID(PRODUCT_ID)
        row.quantity = Decimal("50")
        row.required_date = None
        row.notes = None
        row.status = "PENDING"
        row.created_at = datetime(2026, 5, 28, 10, 0, 0, tzinfo=timezone.utc)

        result_row = MagicMock()
        result_row.name = "Some Node"
        product_row = MagicMock()
        product_row.name = "Product X"
        product_row.sku = "X-001"

        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                MagicMock(fetchone=MagicMock(return_value=result_row)),
                MagicMock(fetchone=MagicMock(return_value=result_row)),
                MagicMock(fetchone=MagicMock(return_value=product_row)),
            ]
        )

        await _enrich(row, session)

        # Inspect the SQL sent for the first warehouse lookup
        first_call = session.execute.call_args_list[0]
        sql_text = str(first_call.args[0])
        assert "organization_node" in sql_text, (
            "_enrich SQL must reference organization_node for COALESCE fallback; got: " + sql_text
        )
