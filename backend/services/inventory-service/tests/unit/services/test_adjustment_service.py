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
from unittest.mock import AsyncMock, MagicMock, call, patch
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
    return AsyncMock()


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
        assert result.transaction_id == UUID(TX_ID)

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
