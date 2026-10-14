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

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Iterator, Optional
from unittest.mock import AsyncMock, MagicMock, call, patch
from uuid import UUID

import pytest
from fastapi import HTTPException

from schemas.inventory import IssueStockRequest, LotPick, ReceiveStockRequest
from services import dispatch_service
from services.dispatch_service import CandidateLot, ProductDispatchInfo
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


NON_BATCH = ProductDispatchInfo(batch_tracking=False, expiry_tracking=False, dispatch_strategy=None)


@pytest.fixture(autouse=True)
def non_batch_product() -> Iterator[AsyncMock]:
    """issue_stock() loads the product first — non-batch unless a test says otherwise."""
    with patch(
        "services.inventory_service.load_product",
        new_callable=AsyncMock,
        return_value=NON_BATCH,
    ) as mock_load:
        yield mock_load


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


# ── FEFO Phase C3 — Issue allocates batch stock per lot ───────────────────────

TODAY = date.today()
# The earliest-expiry lot has the HIGHER lot_id, so "engine order" and
# "sorted by lot_id" are different orders.
LOT_LATE    = "cccccccc-0000-0000-0000-000000000001"
LOT_EARLY   = "cccccccc-0000-0000-0000-000000000002"
LOT_EXPIRED = "cccccccc-0000-0000-0000-000000000003"

FEFO_PRODUCT = ProductDispatchInfo(batch_tracking=True, expiry_tracking=True, dispatch_strategy=None)
FIFO_PRODUCT = ProductDispatchInfo(batch_tracking=True, expiry_tracking=False, dispatch_strategy=None)


def _lot(lot_id: str, number: str, expiry_days: int, received_day: int, qty: str) -> CandidateLot:
    return CandidateLot(
        lot_id=lot_id,
        lot_number=number,
        expiry_date=TODAY + timedelta(days=expiry_days),
        first_received_at=datetime(2026, 1, received_day, tzinfo=timezone.utc),
        quantity=Decimal(qty),
    )


EARLY   = _lot(LOT_EARLY,   "L-EARLY",   10, 1, "20")
LATE    = _lot(LOT_LATE,    "L-LATE",    60, 2, "50")
EXPIRED = _lot(LOT_EXPIRED, "L-EXPIRED", -5, 3, "100")


def _issue_ref(key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"issue:{TENANT_ID}:{key}"))


def _body(
    key: str,
    qty: str,
    picks: Optional[list[tuple[str, str]]] = None,
    reason: Optional[str] = None,
) -> IssueStockRequest:
    return IssueStockRequest(
        product_id=UUID(PRODUCT_ID),
        warehouse_id=UUID(WAREHOUSE_ID),
        quantity=Decimal(qty),
        reason_code="SALE",
        idempotency_key=key,
        lot_selections=(
            [LotPick(lot_id=UUID(l), quantity=Decimal(q)) for l, q in picks] if picks else None
        ),
        override_reason=reason,
    )


class _BatchHarness:
    """Real dispatch engine over fake lots; db.execute and the ledger are mocked.

    events records the order of: "replay" (ISSUE rows lookup), "lock_balance"
    (inventory_balances FOR UPDATE), "load_lots" (candidate lots loaded),
    "override_insert" (lot_allocation_overrides INSERT).
    """

    def __init__(self, lots: list[CandidateLot], issued_rows: Optional[list[Any]] = None) -> None:
        self.lots = lots
        self.issued_rows = issued_rows or []
        self.events: list[str] = []
        self.db = AsyncMock()
        self.db.execute = AsyncMock(side_effect=self._execute)
        self.svc = InventoryService(self.db)
        self.record = AsyncMock(side_effect=lambda *a, **kw: str(uuid.uuid4()))
        self.override: Any = None

    async def _execute(self, stmt: Any, params: Any = None) -> MagicMock:
        sql = str(stmt)
        result = MagicMock()
        result.fetchall.return_value = []
        result.fetchone.return_value = None
        if "FROM inventory_transactions" in sql:
            self.events.append("replay")
            result.fetchall.return_value = list(self.issued_rows)
        elif "FROM inventory_balances" in sql and "FOR UPDATE" in sql:
            self.events.append("lock_balance")
        elif "INSERT INTO lot_allocation_overrides" in sql:
            self.events.append("override_insert")
            result.fetchone.return_value = SimpleNamespace(
                id="dddddddd-0000-0000-0000-000000000001"
            )
        elif "FROM stock_lots" in sql:
            result.fetchall.return_value = [
                SimpleNamespace(id=l.lot_id, lot_number=l.lot_number, expiry_date=l.expiry_date)
                for l in self.lots
            ]
        return result

    async def _load_lots(self, *args: Any, **kwargs: Any) -> list[CandidateLot]:
        self.events.append("load_lots")
        return list(self.lots)

    async def issue(
        self, product: ProductDispatchInfo, body: IssueStockRequest, **flags: bool
    ) -> Any:
        with patch(
            "services.inventory_service.load_product", new_callable=AsyncMock, return_value=product
        ), patch(
            "services.dispatch_service.load_candidate_lots", new=self._load_lots
        ), patch(
            "services.inventory_service.load_candidate_lots", new=self._load_lots
        ), patch(
            "services.inventory_service.record_override",
            new_callable=AsyncMock,
            side_effect=dispatch_service.record_override,
        ) as mock_override, patch(
            "services.inventory_service.record_transaction", new=self.record
        ):
            self.override = mock_override
            return await self.svc.issue_stock(WM, body, **flags)

    def posted(self) -> list[dict[str, Any]]:
        return [c.kwargs for c in self.record.await_args_list]


@pytest.mark.unit
class TestIssueNonBatchUnchanged:

    async def test_non_batch_posts_single_row_with_unchanged_key(
        self, svc: InventoryService
    ) -> None:
        """Non-batch product: exactly the pre-C3 single ISSUE row, lots == []."""
        body = _body("issue:c3:nonbatch", "30")

        with patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock,
            return_value=TX_ID,
        ) as mock_record:
            result = await svc.issue_stock(WM, body)

        mock_record.assert_awaited_once()
        _, kwargs = mock_record.call_args
        assert kwargs["idempotency_key"] == "issue:c3:nonbatch"
        assert kwargs["transaction_type"] == "ISSUE"
        assert kwargs["quantity"] == Decimal("-30")
        assert "lot_id" not in kwargs and "reference_id" not in kwargs
        assert result.transaction_id == UUID(TX_ID)
        assert result.lots == []
        assert result.is_override is False

    async def test_non_batch_with_lot_selections_is_lot_not_tracked(
        self, svc: InventoryService
    ) -> None:
        body = _body("issue:c3:nonbatch-sel", "30", picks=[(LOT_EARLY, "30")])

        with patch(
            "services.inventory_service.record_transaction", new_callable=AsyncMock
        ) as mock_record:
            with pytest.raises(HTTPException) as exc:
                await svc.issue_stock(WM, body, can_fefo_override=True, can_lot_select=True)

        assert exc.value.status_code == 422
        assert exc.value.detail["code"] == "LOT_NOT_TRACKED"
        mock_record.assert_not_awaited()

    async def test_non_batch_replay_returns_the_original_row(self) -> None:
        """Same key resent: record_transaction's 409 becomes the original
        result (its transaction_id and quantity); no second ledger row."""
        original = SimpleNamespace(id=TX_ID, quantity=Decimal("-30.0000"))
        h = _BatchHarness([], issued_rows=[])
        h.db.execute = AsyncMock(return_value=MagicMock(
            fetchone=MagicMock(return_value=original)
        ))
        h.record = AsyncMock(side_effect=HTTPException(
            status_code=409,
            detail={"code": "DUPLICATE_TRANSACTION", "idempotency_key": "issue:nb:replay"},
        ))

        result = await h.issue(
            ProductDispatchInfo(batch_tracking=False, expiry_tracking=False, dispatch_strategy=None),
            _body("issue:nb:replay", "30"),
        )

        h.record.assert_awaited_once()          # the one attempt that hit the key
        assert result.transaction_id == UUID(TX_ID)
        assert result.quantity == Decimal("30")
        assert result.lots == [] and result.is_override is False
        lookup = h.db.execute.await_args
        assert "FROM inventory_transactions" in str(lookup.args[0])
        assert "type = 'ISSUE'" in str(lookup.args[0])
        assert lookup.args[1] == {"tid": TENANT_ID, "key": "issue:nb:replay"}

    async def test_non_batch_key_used_elsewhere_stays_409(self) -> None:
        """409 but no ISSUE row for the key in this tenant → the 409 stands."""
        h = _BatchHarness([], issued_rows=[])
        h.record = AsyncMock(side_effect=HTTPException(
            status_code=409, detail={"code": "DUPLICATE_TRANSACTION"},
        ))

        with pytest.raises(HTTPException) as exc:
            await h.issue(
                ProductDispatchInfo(batch_tracking=False, expiry_tracking=False, dispatch_strategy=None),
                _body("issue:nb:foreign", "30"),
            )

        assert exc.value.status_code == 409
        assert exc.value.detail["code"] == "DUPLICATE_TRANSACTION"


@pytest.mark.unit
class TestIssueBatchEngineAllocation:

    async def test_fefo_split_posts_one_issue_row_per_lot(self) -> None:
        """30 units over EARLY(20) + LATE(50): two ISSUE rows, sorted by lot_id."""
        h = _BatchHarness([EARLY, LATE, EXPIRED])
        key = "issue:c3:fefo-split"

        result = await h.issue(FEFO_PRODUCT, _body(key, "30"))

        rows = h.posted()
        assert [r["lot_id"] for r in rows] == [LOT_LATE, LOT_EARLY]          # sorted by lot_id
        assert [r["quantity"] for r in rows] == [Decimal("-10"), Decimal("-20")]
        assert [r["idempotency_key"] for r in rows] == [
            f"{key}:lot:{LOT_LATE}", f"{key}:lot:{LOT_EARLY}",
        ]
        assert {r["reference_id"] for r in rows} == {_issue_ref(key)}
        assert {r["transaction_type"] for r in rows} == {"ISSUE"}
        assert [r["lot_number"] for r in rows] == ["L-LATE", "L-EARLY"]
        assert [r["expiry_date"] for r in rows] == [LATE.expiry_date, EARLY.expiry_date]

        assert [(str(l.lot_id), l.quantity) for l in result.lots] == [
            (LOT_LATE, Decimal("10")), (LOT_EARLY, Decimal("20")),
        ]
        assert result.quantity == Decimal("30")
        assert result.is_override is False
        h.override.assert_not_awaited()

    async def test_transaction_id_is_first_ledger_row(self) -> None:
        h = _BatchHarness([EARLY, LATE])
        ids = ["eeeeeeee-0000-0000-0000-000000000001", "eeeeeeee-0000-0000-0000-000000000002"]
        h.record = AsyncMock(side_effect=ids)

        result = await h.issue(FEFO_PRODUCT, _body("issue:c3:first-id", "30"))

        assert result.transaction_id == UUID(ids[0])

    async def test_shortfall_with_expired_stock_reports_expired_qty(self) -> None:
        """80 wanted, 70 usable, 100 sitting in an expired lot → 422, nothing posted."""
        h = _BatchHarness([EARLY, LATE, EXPIRED])

        with pytest.raises(HTTPException) as exc:
            await h.issue(FEFO_PRODUCT, _body("issue:c3:shortfall", "80"))

        assert exc.value.status_code == 422
        assert exc.value.detail == {
            "code": "INSUFFICIENT_STOCK",
            "product_id": PRODUCT_ID,
            "requested": 80.0,
            "available": 70.0,
            "expired_qty": 100.0,
        }
        h.record.assert_not_awaited()

    async def test_balance_row_locked_before_candidate_lots_are_loaded(self) -> None:
        """Lock order: replay lookup, inventory_balances FOR UPDATE, then the lots."""
        h = _BatchHarness([EARLY, LATE])

        await h.issue(FEFO_PRODUCT, _body("issue:c3:lock-order", "30"))

        assert h.events[0] == "replay"
        assert "lock_balance" in h.events and "load_lots" in h.events
        assert h.events.index("lock_balance") < h.events.index("load_lots")
        lock_sql = [
            str(c.args[0]) for c in h.db.execute.await_args_list
            if "FROM inventory_balances" in str(c.args[0])
        ]
        assert len(lock_sql) == 1 and "FOR UPDATE" in lock_sql[0]


@pytest.mark.unit
class TestIssueBatchManualSelection:

    async def test_selection_equal_to_engine_order_is_not_an_override(self) -> None:
        h = _BatchHarness([EARLY, LATE])
        body = _body("issue:c3:same", "30", picks=[(LOT_LATE, "10"), (LOT_EARLY, "20")])

        result = await h.issue(FEFO_PRODUCT, body)   # no override permission at all

        assert result.is_override is False
        h.override.assert_not_awaited()
        assert "override_insert" not in h.events
        assert [(r["lot_id"], r["quantity"]) for r in h.posted()] == [
            (LOT_LATE, Decimal("-10")), (LOT_EARLY, Decimal("-20")),
        ]

    async def test_fefo_override_with_permission_and_reason_is_logged(self) -> None:
        h = _BatchHarness([EARLY, LATE])
        key = "issue:c3:fefo-override"
        body = _body(key, "30", picks=[(LOT_LATE, "30")], reason="Customer asked for this lot")

        result = await h.issue(FEFO_PRODUCT, body, can_fefo_override=True)

        h.override.assert_awaited_once()
        kwargs = h.override.await_args.kwargs
        assert kwargs["movement_type"] == "ISSUE"
        assert kwargs["reference_id"] == _issue_ref(key)
        assert kwargs["strategy"] == "FEFO"
        assert kwargs["reason"] == "Customer asked for this lot"
        assert "override_insert" in h.events
        assert result.is_override is True
        # The lots posted are the chosen lots, not the plan.
        assert [(r["lot_id"], r["quantity"]) for r in h.posted()] == [(LOT_LATE, Decimal("-30"))]
        assert [(str(l.lot_id), l.quantity) for l in result.lots] == [(LOT_LATE, Decimal("30"))]

    async def test_fefo_override_without_reason_is_rejected(self) -> None:
        h = _BatchHarness([EARLY, LATE])
        body = _body("issue:c3:no-reason", "30", picks=[(LOT_LATE, "30")], reason="   ")

        with pytest.raises(HTTPException) as exc:
            await h.issue(FEFO_PRODUCT, body, can_fefo_override=True)

        assert exc.value.status_code == 422
        assert exc.value.detail["code"] == "OVERRIDE_REASON_REQUIRED"
        assert "override_insert" not in h.events
        h.record.assert_not_awaited()

    async def test_fefo_override_without_permission_is_forbidden(self) -> None:
        """dispatch:lot_select alone does not permit a FEFO override."""
        h = _BatchHarness([EARLY, LATE])
        body = _body("issue:c3:no-perm", "30", picks=[(LOT_LATE, "30")], reason="why")

        with pytest.raises(HTTPException) as exc:
            await h.issue(FEFO_PRODUCT, body, can_fefo_override=False, can_lot_select=True)

        assert exc.value.status_code == 403
        assert exc.value.detail["code"] == "OVERRIDE_NOT_PERMITTED"
        h.override.assert_not_awaited()
        assert "override_insert" not in h.events
        h.record.assert_not_awaited()

    async def test_fifo_override_allowed_with_lot_select_reason_optional(self) -> None:
        h = _BatchHarness([EARLY, LATE])
        body = _body("issue:c3:fifo-ok", "30", picks=[(LOT_LATE, "30")])   # no reason

        result = await h.issue(FIFO_PRODUCT, body, can_lot_select=True)

        h.override.assert_awaited_once()
        kwargs = h.override.await_args.kwargs
        assert kwargs["strategy"] == "FIFO" and kwargs["movement_type"] == "ISSUE"
        assert kwargs["reason"] is None
        assert result.is_override is True
        assert [(r["lot_id"], r["quantity"]) for r in h.posted()] == [(LOT_LATE, Decimal("-30"))]

    async def test_fifo_override_without_lot_select_is_forbidden(self) -> None:
        """dispatch:fefo_override alone does not permit a FIFO override."""
        h = _BatchHarness([EARLY, LATE])
        body = _body("issue:c3:fifo-403", "30", picks=[(LOT_LATE, "30")])

        with pytest.raises(HTTPException) as exc:
            await h.issue(FIFO_PRODUCT, body, can_fefo_override=True, can_lot_select=False)

        assert exc.value.status_code == 403
        assert exc.value.detail["code"] == "OVERRIDE_NOT_PERMITTED"
        h.record.assert_not_awaited()

    @pytest.mark.parametrize(
        "picks, code",
        [
            ([(LOT_EXPIRED, "30")], "LOT_EXPIRED"),
            ([(LOT_EARLY, "30")], "INSUFFICIENT_LOT_STOCK"),
            ([(LOT_EARLY, "10")], "SELECTION_QTY_MISMATCH"),
            ([("cccccccc-0000-0000-0000-000000000099", "30")], "LOT_NOT_IN_WAREHOUSE"),
        ],
    )
    async def test_selection_errors_pass_through_as_422(
        self, picks: list[tuple[str, str]], code: str
    ) -> None:
        h = _BatchHarness([EARLY, LATE, EXPIRED])
        body = _body(f"issue:c3:{code}", "30", picks=picks, reason="why")

        with pytest.raises(HTTPException) as exc:
            await h.issue(FEFO_PRODUCT, body, can_fefo_override=True, can_lot_select=True)

        assert exc.value.status_code == 422
        assert exc.value.detail["code"] == code
        h.override.assert_not_awaited()
        h.record.assert_not_awaited()


@pytest.mark.unit
class TestIssueBatchReplay:

    async def test_replay_returns_existing_rows_and_writes_nothing(self) -> None:
        """ISSUE rows already exist for issue_ref → returned as-is, nothing allocated."""
        rows = [
            SimpleNamespace(
                id="eeeeeeee-0000-0000-0000-000000000001", lot_id=LOT_LATE,
                lot_number="L-LATE", expiry_date=LATE.expiry_date, quantity=Decimal("-10"),
            ),
            SimpleNamespace(
                id="eeeeeeee-0000-0000-0000-000000000002", lot_id=LOT_EARLY,
                lot_number="L-EARLY", expiry_date=EARLY.expiry_date, quantity=Decimal("-20"),
            ),
        ]
        h = _BatchHarness([EARLY, LATE], issued_rows=rows)
        key = "issue:c3:replay"

        with patch(
            "services.inventory_service.allocate", new_callable=AsyncMock
        ) as mock_allocate, patch(
            "services.inventory_service.validate_manual_selection", new_callable=AsyncMock
        ) as mock_validate:
            result = await h.issue(FEFO_PRODUCT, _body(key, "30"))

        mock_allocate.assert_not_awaited()
        mock_validate.assert_not_awaited()
        h.record.assert_not_awaited()
        h.override.assert_not_awaited()
        assert h.events == ["replay"]          # no lock taken, no lots loaded
        replay_call = h.db.execute.await_args_list[0]
        assert replay_call.args[1] == {"tid": TENANT_ID, "ref": _issue_ref(key)}

        assert result.transaction_id == UUID(rows[0].id)
        assert result.quantity == Decimal("30")
        assert [(str(l.lot_id), l.lot_number, l.quantity) for l in result.lots] == [
            (LOT_LATE, "L-LATE", Decimal("10")), (LOT_EARLY, "L-EARLY", Decimal("20")),
        ]
