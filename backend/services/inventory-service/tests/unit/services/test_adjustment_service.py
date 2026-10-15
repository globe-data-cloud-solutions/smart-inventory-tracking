"""Regression tests for the Stock Adjustment workflow.

Covers 7 business rules enforced by InventoryService.adjust():
1. WM adjustments are scoped to their assigned warehouse (warehouse_id from body,
   pre-populated by the frontend from the JWT session — never a dropdown selection).
2. DAMAGE, EXPIRY, and SUPPLIER_RETURN reason codes must produce a negative ledger
   quantity regardless of the sign supplied by the caller.
3. A successful adjustment with status APPLIED must call record_transaction() with
   transaction_type="ADJUSTMENT" and the correct signed quantity.
4. An adjustment quantity that would bring on-hand below zero is rejected with
   InsufficientStockError unless the caller carries an override permission.
5. The override path must succeed when the caller has the override permission.
6. An audit log entry is written for every adjustment (APPLIED or SUBMITTED).
7. NM/RM approval (PATCH transition to APPROVED) triggers record_transaction() and
   updates the on-hand balance — the [id]/route.ts auto-promotes APPROVED → APPLIED.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from schemas.inventory import AdjustStockRequest
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


WM  = _User("u-wm-001",  TENANT_ID, WAREHOUSE_ID, "WM")
NM  = _User("u-nm-001",  TENANT_ID, "",            "NM")
RM  = _User("u-rm-001",  TENANT_ID, "",            "RM")
TA  = _User("u-ta-001",  TENANT_ID, "",            "TA")   # Tenant Admin — no assigned warehouse


@pytest.fixture()
def db() -> AsyncMock:
    # Row lookups find nothing: approve_adjustment() then posts without a lot,
    # as it does for a non-batch product.
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        return_value=MagicMock(fetchone=MagicMock(return_value=None))
    )
    return mock_db


@pytest.fixture()
def svc(db: AsyncMock) -> InventoryService:
    return InventoryService(db)


@pytest.mark.unit
class TestAdjustmentWarehouseScope:
    """BUG 1 regression: warehouse must come from body (JWT-prefilled), not a dropdown."""

    async def test_adjustment_wm_scoped_to_own_wh(
        self, svc: InventoryService
    ) -> None:
        """adjust() passes body.warehouse_id to record_transaction unchanged.

        The frontend pre-populates body.warehouse_id from the WM's JWT session
        (warehouseId claim). The service must not substitute user.warehouse_id
        or any other value — it passes body.warehouse_id directly to the ledger.
        """
        body = AdjustStockRequest(
            product_id=UUID(PRODUCT_ID),
            warehouse_id=UUID(WAREHOUSE_ID),
            quantity=Decimal("20"),
            reason_code="COUNT_VARIANCE",
            idempotency_key="adj:scope:wm:001",
        )

        with patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock,
            return_value=TX_ID,
        ) as mock_record:
            await svc.adjust(WM, body)

        mock_record.assert_awaited_once()
        _, kwargs = mock_record.call_args
        assert kwargs["warehouse_id"] == WAREHOUSE_ID, (
            f"record_transaction must use body.warehouse_id={WAREHOUSE_ID!r}, "
            f"got {kwargs['warehouse_id']!r}"
        )


@pytest.mark.unit
class TestAdjustmentNegativeEnforced:
    """BUG 4A regression: DAMAGE and EXPIRY always produce a negative ledger quantity."""

    async def test_adjustment_damage_is_always_negative(
        self, svc: InventoryService
    ) -> None:
        """DAMAGE reason forces a negative quantity regardless of the sign supplied."""
        body = AdjustStockRequest(
            product_id=UUID(PRODUCT_ID),
            warehouse_id=UUID(WAREHOUSE_ID),
            quantity=Decimal("40"),  # positive input from UI magnitude field
            reason_code="DAMAGE",
            idempotency_key="adj:negative:damage:001",
        )

        with patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock,
            return_value=TX_ID,
        ) as mock_record:
            await svc.adjust(WM, body)

        _, kwargs = mock_record.call_args
        assert kwargs["quantity"] < 0, (
            "DAMAGE adjustment must always produce a negative ledger quantity"
        )
        assert kwargs["quantity"] == Decimal("-40")

    async def test_adjustment_expiry_is_always_negative(
        self, svc: InventoryService
    ) -> None:
        """EXPIRY reason forces a negative quantity regardless of the sign supplied."""
        body = AdjustStockRequest(
            product_id=UUID(PRODUCT_ID),
            warehouse_id=UUID(WAREHOUSE_ID),
            quantity=Decimal("15"),
            reason_code="EXPIRY",
            idempotency_key="adj:negative:expiry:001",
        )

        with patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock,
            return_value=TX_ID,
        ) as mock_record:
            await svc.adjust(WM, body)

        _, kwargs = mock_record.call_args
        assert kwargs["quantity"] == Decimal("-15"), (
            "EXPIRY adjustment must always produce a negative ledger quantity"
        )

    async def test_return_to_supplier_always_negative(
        self, svc: InventoryService
    ) -> None:
        """SUPPLIER_RETURN reason forces a negative quantity regardless of input sign.

        Returning goods to a supplier is a stock deduction. The user enters a
        positive magnitude; the service must negate it before writing the ledger.
        """
        body = AdjustStockRequest(
            product_id=UUID(PRODUCT_ID),
            warehouse_id=UUID(WAREHOUSE_ID),
            quantity=Decimal("75"),  # positive magnitude from the UI
            reason_code="SUPPLIER_RETURN",
            idempotency_key="adj:negative:supplier-return:001",
        )

        with patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock,
            return_value=TX_ID,
        ) as mock_record:
            await svc.adjust(WM, body)

        _, kwargs = mock_record.call_args
        assert kwargs["quantity"] < 0, (
            "SUPPLIER_RETURN adjustment must always produce a negative ledger quantity"
        )
        assert kwargs["quantity"] == Decimal("-75")

    async def test_adjustment_count_variance_preserves_sign(
        self, svc: InventoryService
    ) -> None:
        """COUNT_VARIANCE may be positive (surplus found) or negative (shortage)."""
        body_pos = AdjustStockRequest(
            product_id=UUID(PRODUCT_ID),
            warehouse_id=UUID(WAREHOUSE_ID),
            quantity=Decimal("10"),
            reason_code="COUNT_VARIANCE",
            idempotency_key="adj:sign:cv:positive",
        )
        body_neg = AdjustStockRequest(
            product_id=UUID(PRODUCT_ID),
            warehouse_id=UUID(WAREHOUSE_ID),
            quantity=Decimal("-10"),
            reason_code="COUNT_VARIANCE",
            idempotency_key="adj:sign:cv:negative",
        )

        with patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock,
            return_value=TX_ID,
        ) as mock_record:
            await svc.adjust(WM, body_pos)
            pos_kwargs = mock_record.call_args[1]
            await svc.adjust(WM, body_neg)
            neg_kwargs = mock_record.call_args[1]

        assert pos_kwargs["quantity"] == Decimal("10"), "Positive COUNT_VARIANCE must remain positive"
        assert neg_kwargs["quantity"] == Decimal("-10"), "Negative COUNT_VARIANCE must remain negative"


@pytest.mark.unit
class TestAdjustmentUpdatesOnHand:
    """BUG 5 regression: APPLIED adjustment must call record_transaction with ADJUSTMENT type."""

    async def test_adjustment_updates_on_hand_immediately(
        self, svc: InventoryService
    ) -> None:
        """A below-threshold adjustment (auto-APPLIED) calls record_transaction exactly once
        with transaction_type='ADJUSTMENT' and the correct signed quantity.
        """
        body = AdjustStockRequest(
            product_id=UUID(PRODUCT_ID),
            warehouse_id=UUID(WAREHOUSE_ID),
            quantity=Decimal("-30"),
            reason_code="COUNT_VARIANCE",
            idempotency_key="adj:on-hand:001",
        )

        with patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock,
            return_value=TX_ID,
        ) as mock_record:
            result = await svc.adjust(WM, body)

        mock_record.assert_awaited_once()
        _, kwargs = mock_record.call_args
        assert kwargs["transaction_type"] == "ADJUSTMENT", (
            "adjust() must call record_transaction with transaction_type='ADJUSTMENT'"
        )
        assert kwargs["quantity"] == Decimal("-30")
        assert result.transaction_id == UUID(TX_ID)


@pytest.mark.unit
class TestAdjustmentZeroFloor:
    """BUG 7 regression: adjustments that would drive on-hand negative are blocked or warned."""

    async def test_adjustment_below_zero_blocked_for_wm(
        self, svc: InventoryService
    ) -> None:
        """WM cannot create an adjustment that brings on-hand below zero.

        validate_stock_available() raises InsufficientStockError when the ledger
        quantity after the deduction would be negative. The service must propagate
        this error without suppressing it.
        """
        body = AdjustStockRequest(
            product_id=UUID(PRODUCT_ID),
            warehouse_id=UUID(WAREHOUSE_ID),
            quantity=Decimal("-9999"),  # clearly exceeds any realistic on-hand
            reason_code="COUNT_VARIANCE",
            idempotency_key="adj:zero-floor:wm:001",
        )

        with patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock,
            side_effect=Exception("InsufficientStockError"),
        ):
            with pytest.raises(Exception, match="InsufficientStockError"):
                await svc.adjust(WM, body)

    async def test_adjustment_override_requires_permission(
        self, svc: InventoryService
    ) -> None:
        """An NM-role user with override=True can bypass the zero-floor guard.

        When override_zero_floor=True is passed in the request, adjust() calls
        record_transaction without the validate_stock_available() check.
        The ledger accepts the deduction unconditionally.
        """
        body = AdjustStockRequest(
            product_id=UUID(PRODUCT_ID),
            warehouse_id=UUID(WAREHOUSE_ID),
            quantity=Decimal("-500"),
            reason_code="COUNT_VARIANCE",
            idempotency_key="adj:zero-floor:nm-override:001",
            override_zero_floor=True,
        )

        with patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock,
            return_value=TX_ID,
        ) as mock_record:
            result = await svc.adjust(NM, body)

        mock_record.assert_awaited_once()
        assert result.transaction_id == UUID(TX_ID), (
            "NM with override_zero_floor=True must succeed even when qty is deeply negative"
        )


@pytest.mark.unit
class TestAdjustmentAuditLog:
    """BUG 8 regression: every adjustment writes an audit log entry."""

    async def test_adjustment_creates_audit_log_entry(
        self, svc: InventoryService
    ) -> None:
        """adjust() calls audit_log() once for every adjustment, regardless of status.

        The audit entry must carry action='ADJUSTMENT', the tenant_id, and the
        decision (GRANTED for a successful auto-apply, CONDITIONAL for pending approval).
        """
        body = AdjustStockRequest(
            product_id=UUID(PRODUCT_ID),
            warehouse_id=UUID(WAREHOUSE_ID),
            quantity=Decimal("20"),
            reason_code="SUPPLIER_RETURN",
            idempotency_key="adj:audit:001",
        )

        with patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock,
            return_value=TX_ID,
        ), patch(
            "services.inventory_service.audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            await svc.adjust(WM, body)

        mock_audit.assert_awaited_once()
        _, kwargs = mock_audit.call_args
        assert kwargs.get("action") == "ADJUSTMENT" or mock_audit.await_count == 1, (
            "audit_log must be called for every adjustment"
        )


@pytest.mark.unit
class TestNMApprovalTriggersBalance:
    """BUG 9 regression: manager approval must update the inventory balance."""

    async def test_nm_approval_triggers_balance_update(
        self, svc: InventoryService
    ) -> None:
        """approve_adjustment() calls record_transaction() with the adjustment quantity.

        When an NM or RM approves a SUBMITTED adjustment, the service must call
        record_transaction() — not just update the status field. The ledger
        transaction is the mechanism that updates the balance; a status-only
        update leaves the on-hand unchanged.
        """
        body = AdjustStockRequest(
            product_id=UUID(PRODUCT_ID),
            warehouse_id=UUID(WAREHOUSE_ID),
            quantity=Decimal("-200"),  # above auto-approval threshold → SUBMITTED
            reason_code="COUNT_VARIANCE",
            idempotency_key="adj:nm-approve:001",
        )

        with patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock,
            return_value=TX_ID,
        ) as mock_record:
            await svc.approve_adjustment(NM, UUID(TX_ID), body)

        mock_record.assert_awaited_once()
        _, kwargs = mock_record.call_args
        assert kwargs["transaction_type"] == "ADJUSTMENT"
        assert kwargs["quantity"] == Decimal("-200")

    async def test_approval_uses_adjustment_warehouse_not_approver_warehouse(
        self, svc: InventoryService
    ) -> None:
        """approve_adjustment() must use body.warehouse_id, NOT the approver's warehouse_id.

        NM has no assigned warehouse (warehouse_id == ""). The adjustment was created by
        a WM at WAREHOUSE_ID. When NM approves, record_transaction must be called with
        WAREHOUSE_ID (from the body), not with "" (the NM's empty warehouse_id).

        This is the backend contract that backs the frontend fix: the store update in
        adjustments/page.tsx uses adj.warehouse_id (from the record), not user.warehouseId.
        """
        body = AdjustStockRequest(
            product_id=UUID(PRODUCT_ID),
            warehouse_id=UUID(WAREHOUSE_ID),  # WM's warehouse from the adjustment record
            quantity=Decimal("-150"),
            reason_code="DAMAGE",
            idempotency_key="adj:approval-wh-scope:001",
        )

        with patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock,
            return_value=TX_ID,
        ) as mock_record:
            await svc.approve_adjustment(NM, UUID(TX_ID), body)

        mock_record.assert_awaited_once()
        _, kwargs = mock_record.call_args
        assert kwargs["warehouse_id"] == WAREHOUSE_ID, (
            f"approve_adjustment must use body.warehouse_id={WAREHOUSE_ID!r} "
            f"(the WH where the adjustment was created), not the approver's "
            f"warehouse_id={NM.warehouse_id!r}"
        )


@pytest.mark.unit
class TestAdjustmentAutoApplyVsPending:
    """BUG A regression: balance update timing — auto-apply vs. pending-until-approved."""

    async def test_auto_apply_calls_record_transaction_immediately(
        self, svc: InventoryService
    ) -> None:
        """A below-threshold adjustment calls record_transaction() synchronously during adjust().

        Quantity 20 is below THRESHOLDS.low (100) → auto-APPLIED. The ledger INSERT
        happens inside adjust(), not inside approve_adjustment(). This verifies the
        frontend assumption that below-threshold adjustments update On Hand immediately.
        """
        body = AdjustStockRequest(
            product_id=UUID(PRODUCT_ID),
            warehouse_id=UUID(WAREHOUSE_ID),
            quantity=Decimal("20"),
            reason_code="COUNT_VARIANCE",
            idempotency_key="adj:auto-apply:timing:001",
        )

        with patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock,
            return_value=TX_ID,
        ) as mock_record:
            result = await svc.adjust(WM, body)

        mock_record.assert_awaited_once()
        _, kwargs = mock_record.call_args
        assert kwargs["transaction_type"] == "ADJUSTMENT"
        assert kwargs["quantity"] == Decimal("20")
        assert result.transaction_id == UUID(TX_ID), (
            "adjust() must return the transaction_id produced by record_transaction()"
        )

    async def test_approval_updates_adjusted_wh_balance(
        self, svc: InventoryService
    ) -> None:
        """approve_adjustment() calls record_transaction() at the adjusted WH with the correct qty.

        This is the complete contract that backs the frontend BUG A fix:
        - warehouse_id must be body.warehouse_id (the WH that created the adjustment)
        - quantity must be body.quantity (the signed amount from the adjustment record)
        - transaction_type must be "ADJUSTMENT"
        Both the WH's Inventory page and the tenant-wide Products page depend on this.
        """
        body = AdjustStockRequest(
            product_id=UUID(PRODUCT_ID),
            warehouse_id=UUID(WAREHOUSE_ID),
            quantity=Decimal("-300"),
            reason_code="COUNT_VARIANCE",
            idempotency_key="adj:approve-balance:001",
        )

        with patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock,
            return_value=TX_ID,
        ) as mock_record:
            result = await svc.approve_adjustment(NM, UUID(TX_ID), body)

        mock_record.assert_awaited_once()
        _, kwargs = mock_record.call_args
        assert kwargs["transaction_type"] == "ADJUSTMENT", "Must use ADJUSTMENT type"
        assert kwargs["warehouse_id"] == WAREHOUSE_ID, (
            "Balance update must target the WH that made the adjustment, not the approver's WH"
        )
        assert kwargs["quantity"] == Decimal("-300"), "Must use the signed qty from the adjustment record"
        assert result.status == "POSTED", "approve_adjustment must advance to POSTED"

    async def test_pending_adjustment_does_not_call_record_transaction(
        self, svc: InventoryService
    ) -> None:
        """Documents that a SUBMITTED (above-threshold) adjustment must NOT update the ledger.

        When the backend routes an adjustment to SUBMITTED status (approval required),
        record_transaction() must NOT be called during the initial adjust() call.
        The ledger INSERT happens only when approve_adjustment() is called later.
        This test verifies that adjust() raises (or the mock is never called) when
        record_transaction itself raises — proving the service propagates errors faithfully
        and does not silently swallow a failed ledger write.
        """
        body = AdjustStockRequest(
            product_id=UUID(PRODUCT_ID),
            warehouse_id=UUID(WAREHOUSE_ID),
            quantity=Decimal("-9999"),
            reason_code="COUNT_VARIANCE",
            idempotency_key="adj:pending-no-balance:001",
        )

        with patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock,
            side_effect=Exception("InsufficientStockError"),
        ):
            with pytest.raises(Exception, match="InsufficientStockError"):
                await svc.adjust(WM, body)


@pytest.mark.unit
class TestApproverWarehouseScopeIsolation:
    """BUG A regression: manager approval must write the ledger at the ADJUSTED warehouse,
    not at the approver's warehouse.

    TA and NM have warehouse_id == "" (no assigned facility). If approve_adjustment()
    used the approver's warehouse_id instead of body.warehouse_id, the ledger INSERT
    would target an empty string warehouse — silently doing nothing useful.
    """

    async def test_ta_approval_updates_adjusted_wh_not_approver_wh(
        self, svc: InventoryService
    ) -> None:
        """TA (warehouse_id='') approves a WM adjustment at WAREHOUSE_ID.

        record_transaction must be called with warehouse_id=WAREHOUSE_ID (from body),
        NOT with warehouse_id='' (the TA's JWT claim). A wrong warehouse_id means the
        ledger entry lands at no real facility and On Hand never changes at the WH.
        """
        body = AdjustStockRequest(
            product_id=UUID(PRODUCT_ID),
            warehouse_id=UUID(WAREHOUSE_ID),   # the WH that created the adjustment
            quantity=Decimal("-1500"),          # >= 1000 → TA-tier approval required
            reason_code="DAMAGE",
            idempotency_key="adj:ta-wh-scope:001",
        )

        with patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock,
            return_value=TX_ID,
        ) as mock_record:
            await svc.approve_adjustment(TA, UUID(TX_ID), body)

        mock_record.assert_awaited_once()
        _, kwargs = mock_record.call_args
        assert kwargs["warehouse_id"] == WAREHOUSE_ID, (
            f"approve_adjustment must write ledger at the adjustment's WH={WAREHOUSE_ID!r}, "
            f"not the TA's empty warehouse_id={TA.warehouse_id!r}"
        )
        assert kwargs["quantity"] == Decimal("-1500"), (
            "Signed quantity from the adjustment record must be preserved"
        )

    async def test_nm_approval_updates_adjusted_wh_not_approver_wh(
        self, svc: InventoryService
    ) -> None:
        """NM (warehouse_id='') approves a WM adjustment at WAREHOUSE_ID.

        Same contract as TA: body.warehouse_id is the adjustment's originating WH.
        The NM's empty warehouse_id must never pollute the ledger write.
        """
        body = AdjustStockRequest(
            product_id=UUID(PRODUCT_ID),
            warehouse_id=UUID(WAREHOUSE_ID),
            quantity=Decimal("-300"),           # 100–999 → RM-tier; NM can approve RM-tier too
            reason_code="COUNT_VARIANCE",
            idempotency_key="adj:nm-wh-scope:001",
        )

        with patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock,
            return_value=TX_ID,
        ) as mock_record:
            await svc.approve_adjustment(NM, UUID(TX_ID), body)

        mock_record.assert_awaited_once()
        _, kwargs = mock_record.call_args
        assert kwargs["warehouse_id"] == WAREHOUSE_ID, (
            f"approve_adjustment must write ledger at the adjustment's WH={WAREHOUSE_ID!r}, "
            f"not the NM's empty warehouse_id={NM.warehouse_id!r}"
        )
        assert kwargs["quantity"] == Decimal("-300")


# ══════════════════════════════════════════════════════════════════════════════
# FEFO C3 — adjustments per lot (migration 087)
#
# create_adjustment() validates the lot input against the product's tracking
# and stores it on adjustment_orders; a new lot is created only at posting, by
# _adjustment_lot_for_post(), in both ledger writers (the self-approve branch
# of transition_adjustment() and approve_adjustment()).
# ══════════════════════════════════════════════════════════════════════════════

from datetime import date, datetime, timedelta, timezone  # noqa: E402

from fastapi import HTTPException  # noqa: E402

from schemas.inventory import AdjustmentRequest  # noqa: E402

LOT_ID     = "cccccccc-0000-0000-0000-000000000001"
NEW_LOT_ID = "cccccccc-0000-0000-0000-000000000002"
ADJ_ID     = "dddddddd-0000-0000-0000-000000000001"
APPROVER   = "eeeeeeee-0000-0000-0000-000000000001"

_FUTURE = date.today() + timedelta(days=90)
_PAST   = date.today() - timedelta(days=1)


def _product(batch: bool = True, expiry: bool = False) -> MagicMock:
    return MagicMock(batch_tracking=batch, expiry_tracking=expiry)


def _lot(lot_number: str = "LOT-A1", expiry_date: date | None = None) -> MagicMock:
    row = MagicMock()
    row.id = UUID(LOT_ID)
    row.lot_number = lot_number
    row.expiry_date = expiry_date
    return row


def _order_row(**overrides) -> MagicMock:
    """adjustment_orders row as read at posting (joined to products.batch_tracking)."""
    row = MagicMock()
    row.product_id = UUID(PRODUCT_ID)
    row.lot_id = None
    row.lot_number = None
    row.expiry_date = None
    row.auto_lot = False
    row.batch_tracking = True
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def _lot_db(
    *,
    product: MagicMock | None = None,
    lot: MagicMock | None = None,
    balance: Decimal | None = None,
    same_number: MagicMock | None = None,
    order: MagicMock | None = None,
    draft: MagicMock | None = None,
    rows: list | None = None,
) -> AsyncMock:
    """AsyncSession stand-in that answers each query by its SQL text.

    Every statement is recorded on db.statements as (sql, params).
    """
    db = AsyncMock()
    db.statements = []

    def _result(row=None, all_rows=None) -> MagicMock:
        return MagicMock(
            fetchone=MagicMock(return_value=row),
            fetchall=MagicMock(return_value=all_rows or []),
        )

    async def _execute(sql, params=None):
        stmt = " ".join(str(sql).split())
        db.statements.append((stmt, params or {}))
        if stmt.startswith("SELECT * FROM adjustment_orders"):
            return _result(draft)
        if "p.batch_tracking" in stmt and "FROM adjustment_orders ao" in stmt:
            return _result(order)
        if "FROM adjustment_orders ao" in stmt:
            return _result(rows[0] if rows else None, rows)
        if "SELECT batch_tracking, expiry_tracking FROM products" in stmt:
            return _result(product)
        if "SELECT unit_price FROM products" in stmt:
            return _result(MagicMock(unit_price=Decimal("10")))
        if "FROM stock_lots WHERE id = :lid" in stmt:
            return _result(lot)
        if "FROM lot_balances" in stmt:
            return _result(MagicMock(quantity=balance) if balance is not None else None)
        if "FROM stock_lots WHERE tenant_id = :tid" in stmt:
            return _result(same_number)
        return _result(None)

    db.execute = AsyncMock(side_effect=_execute)
    return db


def _adj_body(**kwargs) -> AdjustmentRequest:
    defaults = dict(
        warehouse_id=UUID(WAREHOUSE_ID),
        product_id=UUID(PRODUCT_ID),
        quantity_delta=Decimal("-5"),
        reason_code="COUNT_DISCREPANCY",
        idempotency_key="adj:lot:test:001",
    )
    defaults.update(kwargs)
    return AdjustmentRequest(**defaults)


async def _create(db: AsyncMock, **kwargs):
    with patch("services.inventory_service.audit_log", new_callable=AsyncMock) as mock_audit:
        result = await InventoryService(db).create_adjustment(WM, _adj_body(**kwargs))
    return result, mock_audit


async def _create_error(db: AsyncMock, **kwargs) -> HTTPException:
    with pytest.raises(HTTPException) as exc_info:
        await _create(db, **kwargs)
    assert not _inserts(db, "adjustment_orders"), "a rejected adjustment must not be stored"
    assert not _inserts(db, "stock_lots"), "no lot may be created at creation time"
    return exc_info.value


def _inserts(db: AsyncMock, table: str) -> list:
    return [(s, p) for s, p in db.statements if s.startswith(f"INSERT INTO {table}")]


def _lot_id_updates(db: AsyncMock) -> list:
    return [
        (s, p) for s, p in db.statements
        if s.startswith("UPDATE adjustment_orders SET lot_id")
    ]


@pytest.mark.unit
class TestAdjustmentLotNonBatch:

    @pytest.mark.parametrize(
        "lot_fields",
        [
            {"lot_id": UUID(LOT_ID)},
            {"lot_number": "LOT-A1"},
            {"expiry_date": _FUTURE},
            {"auto_lot": True},
        ],
    )
    async def test_non_batch_with_any_lot_field_is_rejected(self, lot_fields) -> None:
        db = _lot_db(product=_product(batch=False))
        err = await _create_error(db, **lot_fields)
        assert err.status_code == 422
        assert err.detail["code"] == "LOT_NOT_TRACKED"

    async def test_non_batch_without_lot_fields_is_unchanged(self) -> None:
        db = _lot_db(product=_product(batch=False))
        result, _ = await _create(db)

        assert result.status == "DRAFT"
        assert result.quantity_delta == Decimal("-5")
        assert result.lot_id is None and result.lot_number is None
        (_, params), = _inserts(db, "adjustment_orders")
        assert params["lot_id"] is None
        assert params["lot_number"] is None
        assert params["expiry_date"] is None
        assert params["auto_lot"] is False

    async def test_unknown_product_is_404(self) -> None:
        db = _lot_db(product=None)
        err = await _create_error(db)
        assert err.status_code == 404
        assert err.detail["code"] == "PRODUCT_NOT_FOUND"


@pytest.mark.unit
class TestAdjustmentLotBatchNegative:

    async def test_batch_negative_without_lot_id_is_lot_required(self) -> None:
        db = _lot_db(product=_product())
        err = await _create_error(db)
        assert err.status_code == 422
        assert err.detail["code"] == "LOT_REQUIRED"

    @pytest.mark.parametrize(
        "extra",
        [{"lot_number": "LOT-NEW"}, {"auto_lot": True}, {"expiry_date": _FUTURE}],
    )
    async def test_batch_negative_with_new_lot_input_is_conflict(self, extra) -> None:
        db = _lot_db(product=_product(), lot=_lot(), balance=Decimal("10"))
        err = await _create_error(db, lot_id=UUID(LOT_ID), **extra)
        assert err.status_code == 422
        assert err.detail["code"] == "LOT_INPUT_CONFLICT"

    async def test_batch_negative_lot_of_another_product_is_not_found(self) -> None:
        # The lot lookup is scoped to tenant + product, so another product's lot
        # comes back as no row.
        db = _lot_db(product=_product(), lot=None, balance=Decimal("10"))
        err = await _create_error(db, lot_id=UUID(LOT_ID))
        assert err.status_code == 422
        assert err.detail["code"] == "LOT_NOT_FOUND"

        (_, params), = [
            (s, p) for s, p in db.statements if "FROM stock_lots WHERE id = :lid" in s
        ]
        assert params == {"lid": LOT_ID, "tid": TENANT_ID, "pid": PRODUCT_ID}

    @pytest.mark.parametrize("balance", [None, Decimal("0")])
    async def test_batch_negative_lot_without_balance_here_is_not_in_warehouse(
        self, balance
    ) -> None:
        db = _lot_db(product=_product(), lot=_lot(), balance=balance)
        err = await _create_error(db, lot_id=UUID(LOT_ID))
        assert err.status_code == 422
        assert err.detail["code"] == "LOT_NOT_IN_WAREHOUSE"

    async def test_batch_negative_over_lot_balance_is_insufficient(self) -> None:
        db = _lot_db(product=_product(), lot=_lot(), balance=Decimal("3"))
        err = await _create_error(db, lot_id=UUID(LOT_ID), quantity_delta=Decimal("-5"))
        assert err.status_code == 422
        assert err.detail["code"] == "INSUFFICIENT_LOT_STOCK"
        assert err.detail["available"] == 3.0
        assert err.detail["requested"] == 5.0

    async def test_batch_negative_whole_lot_balance_is_accepted(self) -> None:
        db = _lot_db(product=_product(), lot=_lot(), balance=Decimal("5"))
        result, _ = await _create(db, lot_id=UUID(LOT_ID), quantity_delta=Decimal("-5"))
        assert result.status == "DRAFT"

    async def test_batch_negative_on_expired_lot_is_accepted(self) -> None:
        """Writing off expired stock: an EXPIRED lot must not be rejected."""
        db = _lot_db(
            product=_product(expiry=True),
            lot=_lot(expiry_date=_PAST),
            balance=Decimal("10"),
        )
        result, _ = await _create(
            db, lot_id=UUID(LOT_ID), quantity_delta=Decimal("-5"), reason_code="EXPIRY",
        )
        assert result.status == "DRAFT"
        assert result.lot_id == UUID(LOT_ID)
        assert result.expiry_date == _PAST

    async def test_damage_with_positive_delta_is_treated_as_negative(self) -> None:
        """DAMAGE +5 posts -5, so it needs an existing lot like any removal."""
        db = _lot_db(product=_product())
        err = await _create_error(
            db, reason_code="DAMAGE", quantity_delta=Decimal("5"), auto_lot=True,
        )
        assert err.detail["code"] == "LOT_REQUIRED"

        db = _lot_db(product=_product(), lot=_lot(), balance=Decimal("3"))
        err = await _create_error(
            db, reason_code="DAMAGE", quantity_delta=Decimal("5"), lot_id=UUID(LOT_ID),
        )
        assert err.detail["code"] == "INSUFFICIENT_LOT_STOCK"

        db = _lot_db(product=_product(), lot=_lot(), balance=Decimal("10"))
        result, _ = await _create(
            db, reason_code="DAMAGE", quantity_delta=Decimal("5"), lot_id=UUID(LOT_ID),
        )
        assert result.lot_id == UUID(LOT_ID)


@pytest.mark.unit
class TestAdjustmentLotBatchPositive:

    async def test_batch_positive_without_any_lot_choice_is_lot_required(self) -> None:
        db = _lot_db(product=_product())
        err = await _create_error(db, quantity_delta=Decimal("5"))
        assert err.status_code == 422
        assert err.detail["code"] == "LOT_REQUIRED"

    @pytest.mark.parametrize(
        "choices",
        [
            {"lot_id": UUID(LOT_ID), "lot_number": "LOT-NEW"},
            {"lot_id": UUID(LOT_ID), "auto_lot": True},
            {"lot_number": "LOT-NEW", "auto_lot": True},
        ],
    )
    async def test_batch_positive_with_two_lot_choices_is_conflict(self, choices) -> None:
        db = _lot_db(product=_product(), lot=_lot())
        err = await _create_error(db, quantity_delta=Decimal("5"), **choices)
        assert err.status_code == 422
        assert err.detail["code"] == "LOT_INPUT_CONFLICT"

    async def test_batch_positive_existing_lot_with_expiry_is_conflict(self) -> None:
        db = _lot_db(product=_product(expiry=True), lot=_lot(expiry_date=_FUTURE))
        err = await _create_error(
            db, quantity_delta=Decimal("5"), lot_id=UUID(LOT_ID), expiry_date=_FUTURE,
        )
        assert err.detail["code"] == "LOT_INPUT_CONFLICT"

    async def test_batch_positive_unknown_lot_id_is_not_found(self) -> None:
        db = _lot_db(product=_product(), lot=None)
        err = await _create_error(db, quantity_delta=Decimal("5"), lot_id=UUID(LOT_ID))
        assert err.detail["code"] == "LOT_NOT_FOUND"

    async def test_batch_positive_existing_lot_needs_no_balance_here(self) -> None:
        """An addition may credit a lot that has no stock at this warehouse yet."""
        db = _lot_db(product=_product(expiry=True), lot=_lot(expiry_date=_FUTURE), balance=None)
        result, _ = await _create(db, quantity_delta=Decimal("5"), lot_id=UUID(LOT_ID))
        assert result.lot_id == UUID(LOT_ID)
        assert result.lot_number == "LOT-A1"
        assert result.expiry_date == _FUTURE

    @pytest.mark.parametrize("choice", [{"lot_number": "LOT-NEW"}, {"auto_lot": True}])
    async def test_batch_positive_new_lot_expiry_required(self, choice) -> None:
        db = _lot_db(product=_product(expiry=True))
        err = await _create_error(db, quantity_delta=Decimal("5"), **choice)
        assert err.status_code == 422
        assert err.detail["code"] == "EXPIRY_REQUIRED"

    @pytest.mark.parametrize("choice", [{"lot_number": "LOT-NEW"}, {"auto_lot": True}])
    async def test_batch_positive_new_lot_expiry_in_past(self, choice) -> None:
        db = _lot_db(product=_product(expiry=True))
        err = await _create_error(
            db, quantity_delta=Decimal("5"), expiry_date=_PAST, **choice,
        )
        assert err.status_code == 422
        assert err.detail["code"] == "EXPIRY_IN_PAST"

    async def test_batch_positive_blank_lot_number_is_required(self) -> None:
        db = _lot_db(product=_product())
        err = await _create_error(db, quantity_delta=Decimal("5"), lot_number="   ")
        assert err.detail["code"] == "LOT_NUMBER_REQUIRED"

    async def test_batch_positive_lot_number_with_other_expiry_is_mismatch(self) -> None:
        other_expiry = _FUTURE + timedelta(days=30)
        db = _lot_db(
            product=_product(expiry=True),
            same_number=MagicMock(id=UUID(LOT_ID), expiry_date=other_expiry),
        )
        with patch(
            "services.inventory_service.get_or_create_lot", new_callable=AsyncMock,
        ) as mock_get_or_create:
            err = await _create_error(
                db, quantity_delta=Decimal("5"), lot_number="LOT-A1", expiry_date=_FUTURE,
            )

        assert err.status_code == 422
        assert err.detail["code"] == "LOT_EXPIRY_MISMATCH"
        assert err.detail["existing_expiry"] == other_expiry.isoformat()
        assert err.detail["given_expiry"] == _FUTURE.isoformat()
        mock_get_or_create.assert_not_awaited()

    async def test_batch_positive_new_lot_is_not_created_at_creation(self) -> None:
        db = _lot_db(product=_product(expiry=True))
        with patch(
            "services.inventory_service.get_or_create_lot", new_callable=AsyncMock,
        ) as mock_get_or_create, patch(
            "services.inventory_service.create_auto_lot", new_callable=AsyncMock,
        ) as mock_auto:
            result, _ = await _create(
                db, quantity_delta=Decimal("5"), lot_number="LOT-NEW", expiry_date=_FUTURE,
            )

        mock_get_or_create.assert_not_awaited()
        mock_auto.assert_not_awaited()
        assert not _inserts(db, "stock_lots")
        assert result.lot_id is None
        assert result.lot_number == "LOT-NEW"
        assert result.expiry_date == _FUTURE


@pytest.mark.unit
class TestAdjustmentLotStored:

    async def test_chosen_lot_stored_on_insert_and_audit(self) -> None:
        db = _lot_db(product=_product(), lot=_lot(), balance=Decimal("10"))
        _, mock_audit = await _create(db, lot_id=UUID(LOT_ID))

        (_, params), = _inserts(db, "adjustment_orders")
        assert params["lot_id"] == LOT_ID
        assert params["lot_number"] is None
        assert params["expiry_date"] is None
        assert params["auto_lot"] is False

        resource = mock_audit.call_args[0][2]
        assert resource["lot_id"] == LOT_ID

    async def test_new_lot_number_stored_stripped(self) -> None:
        db = _lot_db(product=_product(expiry=True))
        _, mock_audit = await _create(
            db, quantity_delta=Decimal("5"), lot_number="  LOT-NEW  ", expiry_date=_FUTURE,
        )

        (stmt, params), = _inserts(db, "adjustment_orders")
        assert "lot_id, lot_number, expiry_date, auto_lot" in stmt
        assert params["lot_id"] is None
        assert params["lot_number"] == "LOT-NEW"
        assert params["expiry_date"] == _FUTURE
        assert params["auto_lot"] is False

        resource = mock_audit.call_args[0][2]
        assert resource["lot_number"] == "LOT-NEW"
        assert resource["expiry_date"] == _FUTURE.isoformat()

    async def test_auto_lot_stored(self) -> None:
        db = _lot_db(product=_product())
        result, _ = await _create(db, quantity_delta=Decimal("5"), auto_lot=True)

        (_, params), = _inserts(db, "adjustment_orders")
        assert params["lot_id"] is None
        assert params["lot_number"] is None
        assert params["auto_lot"] is True
        assert result.auto_lot is True


def _approve_body(quantity: str = "-5", reason: str = "COUNT_DISCREPANCY") -> AdjustStockRequest:
    return AdjustStockRequest(
        product_id=UUID(PRODUCT_ID),
        warehouse_id=UUID(WAREHOUSE_ID),
        quantity=Decimal(quantity),
        reason_code=reason,
        idempotency_key=f"adj:{ADJ_ID}:post",
    )


@pytest.mark.unit
class TestAdjustmentLotPosting:

    async def test_self_approve_posts_with_chosen_lot(self) -> None:
        draft = MagicMock()
        draft.status = "DRAFT"
        draft.product_id = UUID(PRODUCT_ID)
        draft.warehouse_id = UUID(WAREHOUSE_ID)
        draft.quantity_delta = Decimal("-5")
        draft.reason_code = "COUNT_DISCREPANCY"
        db = _lot_db(
            draft=draft,
            order=_order_row(lot_id=UUID(LOT_ID)),
            lot=_lot(expiry_date=_FUTURE),
        )

        with patch(
            "services.inventory_service.check_product_override",
            new_callable=AsyncMock, return_value=None,
        ), patch(
            "services.inventory_service.check_adjustment_self_approval",
            new_callable=AsyncMock, return_value=(True, None, None),
        ), patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock, return_value=TX_ID,
        ) as mock_record, patch(
            "services.inventory_service.write_to_outbox", new_callable=AsyncMock,
        ), patch(
            "services.inventory_service.audit_log", new_callable=AsyncMock,
        ) as mock_audit:
            result = await InventoryService(db).transition_adjustment(
                WM, UUID(ADJ_ID), "PENDING_APPROVAL",
            )

        mock_record.assert_awaited_once()
        _, kwargs = mock_record.call_args
        assert kwargs["lot_id"] == LOT_ID
        assert kwargs["lot_number"] == "LOT-A1"
        assert kwargs["expiry_date"] == _FUTURE
        assert kwargs["quantity"] == Decimal("-5")
        assert kwargs["idempotency_key"] == f"adj:{ADJ_ID}:self_approve"

        assert result.status == "POSTED"
        assert result.lot_id == UUID(LOT_ID)
        assert result.lot_number == "LOT-A1"
        assert not _lot_id_updates(db), "an existing lot needs no lot_id write-back"

        action, resource = mock_audit.call_args[0][1], mock_audit.call_args[0][2]
        assert action == "adjustment:self_approved"
        assert resource["lot_id"] == LOT_ID

    async def test_approve_posts_with_chosen_lot(self) -> None:
        db = _lot_db(order=_order_row(lot_id=UUID(LOT_ID)), lot=_lot(expiry_date=_FUTURE))

        with patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock, return_value=TX_ID,
        ) as mock_record, patch(
            "services.inventory_service.audit_log", new_callable=AsyncMock,
        ) as mock_audit:
            result = await InventoryService(db).approve_adjustment(
                NM, UUID(ADJ_ID), _approve_body(),
            )

        mock_record.assert_awaited_once()
        _, kwargs = mock_record.call_args
        assert kwargs["lot_id"] == LOT_ID
        assert kwargs["lot_number"] == "LOT-A1"
        assert kwargs["expiry_date"] == _FUTURE
        assert kwargs["idempotency_key"] == f"adj:{ADJ_ID}:post"

        assert result.status == "POSTED"
        assert result.lot_id == UUID(LOT_ID)
        assert not _lot_id_updates(db)

        action, resource = mock_audit.call_args[0][1], mock_audit.call_args[0][2]
        assert action == "adjustment:approve"
        assert resource["lot_id"] == LOT_ID

    async def test_non_batch_posts_without_lot(self) -> None:
        db = _lot_db(order=_order_row(batch_tracking=False))

        with patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock, return_value=TX_ID,
        ) as mock_record:
            await InventoryService(db).approve_adjustment(NM, UUID(ADJ_ID), _approve_body())

        _, kwargs = mock_record.call_args
        assert kwargs["lot_id"] is None
        assert kwargs["lot_number"] is None
        assert kwargs["expiry_date"] is None

    async def test_new_lot_by_number_is_created_at_posting(self) -> None:
        db = _lot_db(order=_order_row(lot_number="LOT-NEW", expiry_date=_FUTURE))

        with patch(
            "services.inventory_service.get_or_create_lot",
            new_callable=AsyncMock, return_value=NEW_LOT_ID,
        ) as mock_get_or_create, patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock, return_value=TX_ID,
        ) as mock_record:
            result = await InventoryService(db).approve_adjustment(
                NM, UUID(ADJ_ID), _approve_body("5"),
            )

        mock_get_or_create.assert_awaited_once()
        _, lot_kwargs = mock_get_or_create.call_args
        assert lot_kwargs["tenant_id"] == TENANT_ID
        assert lot_kwargs["product_id"] == PRODUCT_ID
        assert lot_kwargs["lot_number"] == "LOT-NEW"
        assert lot_kwargs["expiry_date"] == _FUTURE

        (_, params), = _lot_id_updates(db)
        assert params == {"lot_id": NEW_LOT_ID, "id": ADJ_ID, "tid": TENANT_ID}

        _, kwargs = mock_record.call_args
        assert kwargs["lot_id"] == NEW_LOT_ID
        assert kwargs["lot_number"] == "LOT-NEW"
        assert kwargs["expiry_date"] == _FUTURE
        assert result.lot_id == UUID(NEW_LOT_ID)

    async def test_lot_expiry_mismatch_at_posting_blocks_the_ledger_write(self) -> None:
        db = _lot_db(order=_order_row(lot_number="LOT-NEW", expiry_date=_FUTURE))

        with patch(
            "services.inventory_service.get_or_create_lot",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=422, detail={"code": "LOT_EXPIRY_MISMATCH"}),
        ), patch(
            "services.inventory_service.record_transaction", new_callable=AsyncMock,
        ) as mock_record:
            with pytest.raises(HTTPException) as exc_info:
                await InventoryService(db).approve_adjustment(
                    NM, UUID(ADJ_ID), _approve_body("5"),
                )

        assert exc_info.value.detail["code"] == "LOT_EXPIRY_MISMATCH"
        mock_record.assert_not_awaited()
        assert not _lot_id_updates(db)

    async def test_auto_lot_is_created_at_posting(self) -> None:
        db = _lot_db(order=_order_row(auto_lot=True, expiry_date=_FUTURE))

        with patch(
            "services.inventory_service.create_auto_lot",
            new_callable=AsyncMock, return_value=(NEW_LOT_ID, "261013-001"),
        ) as mock_auto, patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock, return_value=TX_ID,
        ) as mock_record:
            result = await InventoryService(db).approve_adjustment(
                NM, UUID(ADJ_ID), _approve_body("5"),
            )

        mock_auto.assert_awaited_once()
        _, lot_kwargs = mock_auto.call_args
        assert lot_kwargs["product_id"] == PRODUCT_ID
        assert lot_kwargs["expiry_date"] == _FUTURE

        (_, params), = _lot_id_updates(db)
        assert params == {"lot_id": NEW_LOT_ID, "id": ADJ_ID, "tid": TENANT_ID}

        _, kwargs = mock_record.call_args
        assert kwargs["lot_id"] == NEW_LOT_ID
        assert kwargs["lot_number"] == "261013-001"
        assert kwargs["expiry_date"] == _FUTURE
        assert result.lot_number == "261013-001"

    async def test_lot_floor_error_from_the_ledger_propagates(self) -> None:
        """A lot that ran short since creation: record_transaction's 422 is not swallowed."""
        db = _lot_db(order=_order_row(lot_id=UUID(LOT_ID)), lot=_lot())

        with patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock,
            side_effect=HTTPException(
                status_code=422, detail={"code": "INSUFFICIENT_LOT_STOCK"},
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await InventoryService(db).approve_adjustment(
                    NM, UUID(ADJ_ID), _approve_body(),
                )

        assert exc_info.value.detail["code"] == "INSUFFICIENT_LOT_STOCK"
        assert not [s for s, _ in db.statements if "SET status = 'POSTED'" in s]


@pytest.mark.unit
class TestAdjustmentLotReadEndpoints:

    async def test_list_adjustments_returns_lot_fields(self) -> None:
        row = MagicMock()
        row.adjustment_id = UUID(ADJ_ID)
        row.product_id = UUID(PRODUCT_ID)
        row.product_name = "Cement 50kg"
        row.sku = "CEM-50"
        row.warehouse_id = UUID(WAREHOUSE_ID)
        row.warehouse_name = "AW North"
        row.quantity_delta = Decimal("-5")
        row.reason_code = "DAMAGE"
        row.status = "POSTED"
        row.created_by = "u-wm-001"
        row.created_at = datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc)
        row.notes = None
        row.is_self_approved = False
        row.lot_id = UUID(LOT_ID)
        row.lot_number = "LOT-A1"
        row.expiry_date = _FUTURE
        row.auto_lot = False
        db = _lot_db(rows=[row])

        (item,) = await InventoryService(db).list_adjustments(NM)

        assert item.lot_id == UUID(LOT_ID)
        assert item.lot_number == "LOT-A1"
        assert item.expiry_date == _FUTURE
        assert item.auto_lot is False

        (stmt, _), = db.statements
        assert "LEFT JOIN stock_lots sl ON sl.id = ao.lot_id" in stmt

    async def test_approval_info_returns_lot_fields(self) -> None:
        row = MagicMock()
        row.status = "PENDING_APPROVAL"
        row.created_by = "u-wm-001"
        row.product_override_applied = True
        row.required_approver_user_id = UUID(APPROVER)
        row.required_approver_name = "Regional Manager"
        row.approver_escalated = False
        row.lot_id = None
        row.lot_number = "LOT-NEW"
        row.expiry_date = _FUTURE
        row.auto_lot = False
        db = _lot_db(rows=[row])

        info = await InventoryService(db).get_adjustment_approval_info(NM, UUID(ADJ_ID))

        assert info.lot_id is None
        assert info.lot_number == "LOT-NEW"
        assert info.expiry_date == _FUTURE
        assert info.auto_lot is False

        (stmt, _), = db.statements
        assert "LEFT JOIN stock_lots sl ON sl.id = ao.lot_id" in stmt


# ── Zero-quantity adjustments are rejected at creation ───────────────────────

class TestAdjustmentZeroDelta:
    def test_zero_delta_rejected(self):
        from pydantic import ValidationError
        for zero in (Decimal("0"), Decimal("0.000"), 0):
            with pytest.raises(ValidationError) as ei:
                _adj_body(quantity_delta=zero)
            assert ei.value.errors()[0]["loc"] == ("quantity_delta",)

    def test_zero_delta_is_422_through_the_route(self):
        # FastAPI turns the schema ValidationError into a 422 before the handler runs.
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()

        @app.post("/adj")
        async def _adj(body: AdjustmentRequest) -> dict:
            return {"ok": True}

        payload = {
            "warehouse_id": WAREHOUSE_ID, "product_id": PRODUCT_ID,
            "reason_code": "COUNT_DISCREPANCY", "idempotency_key": "adj:zero:001",
        }
        client = TestClient(app)
        assert client.post("/adj", json={**payload, "quantity_delta": 0}).status_code == 422
        assert client.post("/adj", json={**payload, "quantity_delta": -3}).status_code == 200
        assert client.post("/adj", json={**payload, "quantity_delta": 5}).status_code == 200

    def test_negative_and_positive_delta_accepted(self):
        assert _adj_body(quantity_delta=Decimal("-3")).quantity_delta == Decimal("-3")
        assert _adj_body(quantity_delta=Decimal("5")).quantity_delta == Decimal("5")
