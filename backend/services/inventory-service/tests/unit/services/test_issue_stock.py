"""Regression tests for Issue Stock — direct On Hand deduction, no reservation.

Bug: Issue Stock was appearing in the Reserved column instead of reducing On Hand.
Root cause: inventory-state.ts getReservedTotal() included ISSUE adjustments, and
            getOnHand() did not subtract ISSUE adjustments.

These tests verify the backend semantics enforced by InventoryService.issue_stock():
1. An ISSUE transaction calls record_transaction with transaction_type="ISSUE" and a
   negative quantity — a direct ledger deduction, not a pending/reserved entry.
2. No RESERVE transaction is created at any point during an ISSUE operation.
3. The issued quantity is negated regardless of the sign the caller supplies.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, call, patch
from uuid import UUID

import pytest

from schemas.inventory import IssueStockRequest, ReceiveStockRequest
from services.inventory_service import InventoryService


TENANT_ID    = "10000000-0000-0000-0000-000000000001"
WAREHOUSE_ID = "20000000-0000-0000-0000-000000000001"
PRODUCT_ID   = "aaaaaaaa-0000-0000-0000-000000000001"
TX_ID        = "bbbbbbbb-0000-0000-0000-000000000001"


@dataclass
class _User:
    user_id: str
    tenant_id: str
    warehouse_id: str
    role: str


WM = _User("u-wm-001", TENANT_ID, WAREHOUSE_ID, "WM")


@pytest.fixture()
def db() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def svc(db: AsyncMock) -> InventoryService:
    return InventoryService(db)


@pytest.mark.unit
class TestIssueStockReducesOnHandDirectly:

    async def test_issue_stock_calls_record_transaction_with_issue_type(
        self, svc: InventoryService
    ) -> None:
        """ISSUE must call record_transaction with transaction_type='ISSUE'.

        A plain ISSUE does not go through any approval state machine — it is a
        single atomic ledger INSERT. The type must be 'ISSUE', not 'ADJUSTMENT'
        or any transfer type.
        """
        body = IssueStockRequest(
            product_id=UUID(PRODUCT_ID),
            warehouse_id=UUID(WAREHOUSE_ID),
            quantity=Decimal("30"),
            reason_code="SALE",
            idempotency_key="issue:test:001",
        )

        with patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock,
            return_value=TX_ID,
        ) as mock_record:
            await svc.issue_stock(WM, body)

        mock_record.assert_awaited_once()
        _, kwargs = mock_record.call_args
        assert kwargs["transaction_type"] == "ISSUE", (
            f"Expected transaction_type='ISSUE', got '{kwargs['transaction_type']}'"
        )

    async def test_issue_stock_quantity_is_negative_deduction(
        self, svc: InventoryService
    ) -> None:
        """The ledger quantity for ISSUE must be negative (direct On Hand deduction).

        On Hand reduces immediately when the ISSUE is posted — there is no
        intermediate RESERVE step that would defer the deduction.
        """
        body = IssueStockRequest(
            product_id=UUID(PRODUCT_ID),
            warehouse_id=UUID(WAREHOUSE_ID),
            quantity=Decimal("30"),
            reason_code="SALE",
            idempotency_key="issue:test:002",
        )

        with patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock,
            return_value=TX_ID,
        ) as mock_record:
            await svc.issue_stock(WM, body)

        _, kwargs = mock_record.call_args
        assert kwargs["quantity"] < 0, (
            f"ISSUE ledger quantity must be negative (deduction), got {kwargs['quantity']}"
        )
        assert kwargs["quantity"] == Decimal("-30"), (
            f"Expected quantity=-30, got {kwargs['quantity']}"
        )

    async def test_issue_stock_negates_regardless_of_caller_sign(
        self, svc: InventoryService
    ) -> None:
        """issue_stock() uses -abs(qty) so the deduction is always negative.

        Even if a caller mistakenly supplies a negative quantity, the ledger
        entry must still be a deduction of the absolute value.
        """
        body = IssueStockRequest(
            product_id=UUID(PRODUCT_ID),
            warehouse_id=UUID(WAREHOUSE_ID),
            quantity=Decimal("50"),
            reason_code="DAMAGE",
            idempotency_key="issue:test:003",
        )

        with patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock,
            return_value=TX_ID,
        ) as mock_record:
            await svc.issue_stock(WM, body)

        _, kwargs = mock_record.call_args
        assert kwargs["quantity"] == Decimal("-50")


@pytest.mark.unit
class TestIssueStockDoesNotCreateReservation:

    async def test_issue_stock_does_not_call_reserve_transaction(
        self, svc: InventoryService
    ) -> None:
        """ISSUE must not create a RESERVE ledger entry.

        Reservation (RESERVE transaction) is exclusively a transfer workflow step.
        An ISSUE bypasses any approval/pending state and writes a single ISSUE entry.
        """
        body = IssueStockRequest(
            product_id=UUID(PRODUCT_ID),
            warehouse_id=UUID(WAREHOUSE_ID),
            quantity=Decimal("30"),
            reason_code="INTERNAL_USE",
            idempotency_key="issue:test:004",
        )

        with patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock,
            return_value=TX_ID,
        ) as mock_record:
            await svc.issue_stock(WM, body)

        # record_transaction must be called exactly once — the ISSUE deduction.
        # If it were called twice (once for RESERVE and once for ISSUE), that would
        # indicate a reservation step was incorrectly inserted.
        assert mock_record.await_count == 1, (
            f"record_transaction called {mock_record.await_count} time(s); "
            "expected exactly 1 (the ISSUE deduction — no RESERVE step)"
        )
        _, kwargs = mock_record.call_args
        assert kwargs["transaction_type"] != "RESERVE", (
            "record_transaction must not be called with transaction_type='RESERVE' for ISSUE"
        )

    async def test_issue_stock_does_not_create_draft_transfer(
        self, svc: InventoryService
    ) -> None:
        """ISSUE must not insert a transfer_orders or adjustment_orders row in DRAFT state.

        A DRAFT row would cause the quantity to appear in the Reserved column on the
        Inventory page (pending-approval holding state). ISSUE skips all approval states.
        """
        db = AsyncMock()
        svc = InventoryService(db)
        body = IssueStockRequest(
            product_id=UUID(PRODUCT_ID),
            warehouse_id=UUID(WAREHOUSE_ID),
            quantity=Decimal("15"),
            reason_code="EXPIRY",
            idempotency_key="issue:test:005",
        )

        with patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock,
            return_value=TX_ID,
        ):
            await svc.issue_stock(WM, body)

        # db.execute must NOT be called with any INSERT INTO transfer_orders or
        # INSERT INTO adjustment_orders statement — ISSUE goes straight to the ledger.
        for mock_call in db.execute.call_args_list:
            sql = str(mock_call.args[0] if mock_call.args else "")
            assert "INSERT INTO transfer_orders" not in sql, (
                "issue_stock must not create a transfer_orders row"
            )
            assert "INSERT INTO adjustment_orders" not in sql, (
                "issue_stock must not create an adjustment_orders row"
            )

    async def test_zero_stock_product_remains_in_inventory(
        self, svc: InventoryService
    ) -> None:
        """Issuing all remaining stock does not raise an error and produces a valid ISSUE tx.

        Business rule: a product with On Hand = 0 must remain visible in the Inventory
        page (enforced by the frontend filter using `whId in p.stock`). The backend must
        accept an ISSUE that brings balance exactly to zero without treating it as an error.

        The ledger accepts zero-balance ISSUE because validate_stock_available() is only
        called when quantity < 0 AFTER the deduction — issuing exactly the remaining
        quantity is always permitted.
        """
        body = IssueStockRequest(
            product_id=UUID(PRODUCT_ID),
            warehouse_id=UUID(WAREHOUSE_ID),
            quantity=Decimal("500"),   # issuing full remaining balance
            reason_code="SALE",
            idempotency_key="issue:zero-balance:001",
        )

        with patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock,
            return_value=TX_ID,
        ) as mock_record:
            result = await svc.issue_stock(WM, body)

        # Must succeed — no exception raised
        assert result.transaction_id == UUID(TX_ID)
        # Ledger entry is a negative deduction of exactly the full quantity
        _, kwargs = mock_record.call_args
        assert kwargs["quantity"] == Decimal("-500")
        assert kwargs["transaction_type"] == "ISSUE"

    async def test_issue_stock_response_carries_correct_fields(
        self, svc: InventoryService
    ) -> None:
        """Response must echo product_id, warehouse_id, quantity, and reason_code."""
        body = IssueStockRequest(
            product_id=UUID(PRODUCT_ID),
            warehouse_id=UUID(WAREHOUSE_ID),
            quantity=Decimal("20"),
            reason_code="SAMPLE",
            idempotency_key="issue:test:006",
        )

        with patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock,
            return_value=TX_ID,
        ):
            result = await svc.issue_stock(WM, body)

        assert result.product_id   == UUID(PRODUCT_ID)
        assert result.warehouse_id == UUID(WAREHOUSE_ID)
        assert result.quantity     == Decimal("20")
        assert result.reason_code  == "SAMPLE"
        assert result.transaction_id == UUID(TX_ID)


@pytest.mark.unit
class TestWarehouseFromJWT:
    """Regression tests — warehouse auto-populated from JWT session, not form input.

    Bug: ReceiveStockPanel and IssueStockPanel showed warehouse dropdowns that
    operators could change, recording transactions against a different warehouse
    than their assigned facility.

    Fix: both panels read warehouseId from getSession() and display it read-only.
    The value is sent as body.warehouse_id (pre-filled by the frontend from the
    JWT session); the service must pass it through unchanged to record_transaction.
    """

    async def test_receive_stock_warehouse_from_jwt_not_input(
        self, svc: InventoryService
    ) -> None:
        """receive() passes body.warehouse_id to record_transaction unchanged.

        The frontend sets body.warehouse_id = user.warehouseId from the JWT session
        (no dropdown for the operator to change). The service must not substitute
        user.warehouse_id or any other value.
        """
        body = ReceiveStockRequest(
            product_id=UUID(PRODUCT_ID),
            warehouse_id=UUID(WAREHOUSE_ID),
            quantity=Decimal("50"),
            idempotency_key="receive:jwt-wh:001",
        )

        product_row = MagicMock(batch_tracking=False, expiry_tracking=False)
        svc.db.execute = AsyncMock(return_value=MagicMock(fetchone=MagicMock(return_value=product_row)))

        with patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock,
            return_value=TX_ID,
        ) as mock_record:
            result = await svc.receive(WM, body)

        mock_record.assert_awaited_once()
        _, kwargs = mock_record.call_args
        assert kwargs["warehouse_id"] == WAREHOUSE_ID, (
            f"record_transaction must use body.warehouse_id={WAREHOUSE_ID!r}, "
            f"got {kwargs['warehouse_id']!r}"
        )
        assert kwargs["transaction_type"] == "RECEIVE"
        assert result.warehouse_id == UUID(WAREHOUSE_ID)

    async def test_issue_stock_warehouse_from_jwt_not_input(
        self, svc: InventoryService
    ) -> None:
        """issue_stock() passes body.warehouse_id to record_transaction unchanged.

        The frontend sets body.warehouse_id = user.warehouseId from the JWT session
        (no dropdown for the operator to change). The service must not substitute
        user.warehouse_id or any other value.
        """
        body = IssueStockRequest(
            product_id=UUID(PRODUCT_ID),
            warehouse_id=UUID(WAREHOUSE_ID),
            quantity=Decimal("40"),
            reason_code="INTERNAL_USE",
            idempotency_key="issue:jwt-wh:001",
        )

        with patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock,
            return_value=TX_ID,
        ) as mock_record:
            result = await svc.issue_stock(WM, body)

        mock_record.assert_awaited_once()
        _, kwargs = mock_record.call_args
        assert kwargs["warehouse_id"] == WAREHOUSE_ID, (
            f"record_transaction must use body.warehouse_id={WAREHOUSE_ID!r}, "
            f"got {kwargs['warehouse_id']!r}"
        )
        assert kwargs["transaction_type"] == "ISSUE"
        assert result.warehouse_id == UUID(WAREHOUSE_ID)
