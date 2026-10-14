from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _no_null(v: object) -> object:
    if isinstance(v, str) and '\x00' in v:
        raise ValueError("Null bytes are not allowed in text fields")
    return v


class AdjustmentReasonCode(str, Enum):
    DAMAGE = "DAMAGE"
    EXPIRY = "EXPIRY"
    THEFT = "THEFT"
    COUNT_DISCREPANCY = "COUNT_DISCREPANCY"
    RETURN = "RETURN"
    PRODUCTION_USE = "PRODUCTION_USE"
    SAMPLE = "SAMPLE"
    OTHER = "OTHER"
    # backward compat: values that may exist in adjustment_orders.reason_code
    # from before this enum was introduced — accepted by backend, not shown in UI
    SUPPLIER_RETURN = "SUPPLIER_RETURN"
    COUNT_VARIANCE = "COUNT_VARIANCE"
    SYSTEM_CORRECTION = "SYSTEM_CORRECTION"


ALLOWED_RECEIVE_SOURCES = frozenset({"WEB", "OPENING_BALANCE"})

ALLOWED_DISPATCH_STRATEGIES = frozenset({"FEFO", "FIFO", "LIFO"})


class FeatureFlagsResponse(BaseModel):
    lot_tracking: bool


class LotSettingsRequest(BaseModel):
    batch_tracking: bool
    expiry_tracking: bool
    dispatch_strategy: Optional[str] = None

    @field_validator("dispatch_strategy", mode="before")
    @classmethod
    def upper_strategy(cls, v: object) -> object:
        return v.strip().upper() if isinstance(v, str) else v


class SetLotExpiryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expiry_date: date


class SetLotExpiryOut(BaseModel):
    lot_id: uuid.UUID
    lot_number: str
    product_id: uuid.UUID
    expiry_date: date


class NearExpirySettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    near_expiry_days: int = Field(..., ge=1, le=365)


class NearExpirySettingsOut(BaseModel):
    near_expiry_days: int


class OpeningLotItem(BaseModel):
    warehouse_id: uuid.UUID
    lot_id: uuid.UUID
    lot_number: str
    quantity: Decimal


class LotSettingsResponse(BaseModel):
    batch_tracking: bool
    expiry_tracking: bool
    dispatch_strategy: Optional[str] = None
    opening_lots: List[OpeningLotItem]


class ReceiveStockRequest(BaseModel):
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    unit_cost: Optional[Decimal] = None
    lot_number: Optional[str] = None
    expiry_date: Optional[date] = None
    auto_lot: bool = False
    idempotency_key: str
    source: str = "WEB"

    @field_validator("lot_number", "idempotency_key", "source", mode="before")
    @classmethod
    def no_null_bytes(cls, v: object) -> object: return _no_null(v)

    @field_validator("lot_number", mode="after")
    @classmethod
    def empty_to_none(cls, v: Optional[str]) -> Optional[str]:
        stripped = v.strip() if v else ""
        return stripped or None


class ReceiveStockResponse(BaseModel):
    transaction_id: uuid.UUID
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    quantity: Decimal
    created_at: datetime
    lot_id: Optional[uuid.UUID] = None
    lot_number: Optional[str] = None
    expiry_date: Optional[date] = None
    source: str


class TransferOrderRequest(BaseModel):
    transfer_type: str = "PULL"
    from_warehouse_id: uuid.UUID
    to_warehouse_id: uuid.UUID
    lines: List[TransferLineRequest]
    notes: Optional[str] = Field(None, max_length=2000)
    transfer_type_config_id: Optional[uuid.UUID] = None

    @field_validator("notes", "transfer_type", mode="before")
    @classmethod
    def no_null_bytes(cls, v: object) -> object: return _no_null(v)


class TransferLineRequest(BaseModel):
    product_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    lot_number: Optional[str] = None

    @field_validator("lot_number", mode="before")
    @classmethod
    def no_null_bytes(cls, v: object) -> object: return _no_null(v)


class TransferLotAllocation(BaseModel):
    """One lot a transfer line was split into at approval (transfer_line_allocations)."""
    line_id: uuid.UUID
    product_id: uuid.UUID
    lot_id: uuid.UUID
    lot_number: Optional[str] = None
    expiry_date: Optional[date] = None
    quantity: Decimal
    is_override: bool = False


class ReceiptLineIn(BaseModel):
    """What arrived for one transfer line (non-batch) or one lot of a line (batch)."""
    line_id: uuid.UUID
    lot_id: Optional[uuid.UUID] = None
    # 4 decimal places = NUMERIC(15,4) on transfer_discrepancies.
    received_quantity: Decimal = Field(ge=0, max_digits=15, decimal_places=4)
    reason: Optional[Literal["SHORT", "DAMAGED", "WRONG_LOT"]] = None
    note: Optional[str] = Field(None, max_length=500)

    @field_validator("note", mode="before")
    @classmethod
    def no_null_bytes(cls, v: object) -> object: return _no_null(v)


class ReceiveTransferRequest(BaseModel):
    lines: List[ReceiptLineIn] = Field(min_length=1)


class TransferDiscrepancyOut(BaseModel):
    """One shortfall recorded at receipt (transfer_discrepancies)."""
    id: uuid.UUID
    transfer_line_id: uuid.UUID
    product_id: uuid.UUID
    lot_id: Optional[uuid.UUID] = None
    lot_number: Optional[str] = None
    sent_quantity: Decimal
    received_quantity: Decimal
    missing_quantity: Decimal
    reason: str
    note: Optional[str] = None
    status: str
    created_at: datetime
    # Set once, when the row is resolved (OPEN -> RESOLVED, 088).
    resolution: Optional[str] = None
    resolved_lot_id: Optional[uuid.UUID] = None
    resolved_lot_number: Optional[str] = None
    resolution_note: Optional[str] = None
    resolved_by: Optional[uuid.UUID] = None
    resolved_at: Optional[datetime] = None


class TransferDiscrepancyListItem(TransferDiscrepancyOut):
    """A discrepancy row with the transfer it belongs to (GET /transfers/discrepancies)."""
    transfer_order_id: uuid.UUID
    transfer_type: str
    from_warehouse_id: uuid.UUID
    to_warehouse_id: uuid.UUID


class ResolveDiscrepancyRequest(BaseModel):
    """How an OPEN discrepancy was settled. lot_id is the lot that actually
    arrived — RECEIVED_AS_LOT only."""
    model_config = ConfigDict(extra="forbid")

    resolution: Literal["WRITTEN_OFF", "RETURNED", "ARRIVED_LATE", "RECEIVED_AS_LOT"]
    lot_id: Optional[uuid.UUID] = None
    note: Optional[str] = Field(None, max_length=500)

    @field_validator("note", mode="before")
    @classmethod
    def no_null_bytes(cls, v: object) -> object: return _no_null(v)


class TransferLineItem(BaseModel):
    line_id: uuid.UUID
    product_id: uuid.UUID
    product_name: str
    sku: str
    quantity: Decimal
    uom: str


class TransferOrderResponse(BaseModel):
    transfer_id: uuid.UUID
    transfer_type: str
    status: str
    from_warehouse_id: uuid.UUID
    to_warehouse_id: uuid.UUID
    created_at: datetime
    # Filled by get_transfer only; other callers leave them None.
    reference_number: Optional[str] = None
    from_warehouse_name: Optional[str] = None
    to_warehouse_name: Optional[str] = None
    total_value: Optional[Decimal] = None
    currency: Optional[str] = None
    transfer_type_config_id: Optional[uuid.UUID] = None
    is_self_approved: bool = False
    current_approval_step: Optional[int] = None
    resolved_approval_steps: Optional[list] = None
    lines: List[TransferLineItem] = []
    lot_allocations: list[TransferLotAllocation] = []
    discrepancies: list[TransferDiscrepancyOut] = []


class LotPick(BaseModel):
    lot_id: uuid.UUID
    quantity: Decimal = Field(gt=0)


class LineLotSelection(BaseModel):
    line_id: uuid.UUID
    lots: List[LotPick] = Field(min_length=1)


class TransferApproveRequest(BaseModel):
    lot_selections: Optional[List[LineLotSelection]] = None
    override_reason: Optional[str] = Field(None, max_length=500)

    @field_validator("override_reason", mode="before")
    @classmethod
    def no_null_bytes(cls, v: object) -> object: return _no_null(v)


class TransferActionRequest(BaseModel):
    notes: Optional[str] = None

    @field_validator("notes", mode="before")
    @classmethod
    def no_null_bytes(cls, v: object) -> object: return _no_null(v)


class AdjustmentRequest(BaseModel):
    warehouse_id: uuid.UUID
    product_id: uuid.UUID
    quantity_delta: Decimal
    reason_code: AdjustmentReasonCode
    lot_id: Optional[uuid.UUID] = None
    lot_number: Optional[str] = None
    expiry_date: Optional[date] = None
    auto_lot: bool = False
    idempotency_key: str
    notes: Optional[str] = Field(None, max_length=2000)

    @field_validator("lot_number", "idempotency_key", "notes", mode="before")
    @classmethod
    def no_null_bytes(cls, v: object) -> object: return _no_null(v)

    @field_validator("quantity_delta", mode="after")
    @classmethod
    def non_zero_delta(cls, v: Decimal) -> Decimal:
        if v == 0:
            raise ValueError("quantity_delta must be non-zero")
        return v


class AdjustmentResponse(BaseModel):
    adjustment_id: uuid.UUID
    status: str
    quantity_delta: Decimal
    created_at: datetime
    is_self_approved: bool = False
    total_value: Optional[Decimal] = None
    # Lot posted (POSTED) or chosen / entered so far (before posting).
    lot_id: Optional[uuid.UUID] = None
    lot_number: Optional[str] = None
    expiry_date: Optional[date] = None
    auto_lot: bool = False


class CountSessionRequest(BaseModel):
    warehouse_id: uuid.UUID
    product_ids: Optional[List[uuid.UUID]] = None
    notes: Optional[str] = None

    @field_validator("notes", mode="before")
    @classmethod
    def no_null_bytes(cls, v: object) -> object: return _no_null(v)


class CountSessionResponse(BaseModel):
    session_id: uuid.UUID
    warehouse_id: uuid.UUID
    status: str
    created_at: datetime


class IssueStockRequest(BaseModel):
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    reason_code: str
    issued_to: Optional[str] = None
    notes: Optional[str] = None
    idempotency_key: str
    source: str = "WEB"
    lot_selections: Optional[List[LotPick]] = None
    override_reason: Optional[str] = Field(None, max_length=500)

    @field_validator(
        "reason_code", "issued_to", "notes", "idempotency_key", "source", "override_reason",
        mode="before",
    )
    @classmethod
    def no_null_bytes(cls, v: object) -> object: return _no_null(v)


class IssuedLot(BaseModel):
    lot_id: uuid.UUID
    lot_number: Optional[str] = None
    expiry_date: Optional[date] = None
    quantity: Decimal


class IssueStockResponse(BaseModel):
    transaction_id: uuid.UUID
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    quantity: Decimal
    reason_code: str
    created_at: datetime
    lots: List[IssuedLot] = []
    is_override: bool = False


class LotSelection(BaseModel):
    lot_id: uuid.UUID
    lot_number: Optional[str]
    quantity: Decimal
    strategy_applied: str


class LotChoice(BaseModel):
    """One line of a user's manual lot selection (dispatch_service.validate_manual_selection)."""
    lot_id: uuid.UUID
    quantity: Decimal = Field(gt=0)


class AllocationLineOut(BaseModel):
    lot_id: uuid.UUID
    lot_number: str
    expiry_date: Optional[date] = None
    quantity: Decimal


class DispatchPreviewResponse(BaseModel):
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    quantity: Decimal
    strategy: Optional[str] = None
    strategy_source: str
    lines: List[AllocationLineOut]
    shortfall: Decimal
    expired_skipped: List[AllocationLineOut]
    available_total: Decimal


class AdjustStockRequest(BaseModel):
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    quantity: Decimal            # signed: positive = add, negative = remove
    reason_code: AdjustmentReasonCode
    notes: Optional[str] = None
    idempotency_key: str
    source: str = "WEB"
    override_zero_floor: bool = False

    @field_validator("notes", "idempotency_key", "source", mode="before")
    @classmethod
    def no_null_bytes(cls, v: object) -> object: return _no_null(v)


class AdjustStockResponse(BaseModel):
    transaction_id: uuid.UUID
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    quantity: Decimal
    reason_code: str
    created_at: datetime


# ── List response schemas ──────────────────────────────────────────────────────

class TransferListItem(BaseModel):
    transfer_id: uuid.UUID
    transfer_type: str
    status: str
    from_warehouse_id: uuid.UUID
    from_warehouse_name: str
    to_warehouse_id: uuid.UUID
    to_warehouse_name: str
    created_by: str
    created_by_authority_level: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    is_self_approved: bool = False
    lines: List[TransferLineItem]
    current_step: int = 1
    total_steps:  int = 1


class TransferTransitionRequest(BaseModel):
    next_status: str


class AdjustmentListItem(BaseModel):
    adjustment_id: uuid.UUID
    product_id: uuid.UUID
    product_name: str
    sku: str
    warehouse_id: uuid.UUID
    warehouse_name: str
    quantity_delta: Decimal
    reason_code: str
    status: str
    created_by: str
    created_at: datetime
    notes: Optional[str] = None
    is_self_approved: bool = False
    lot_id: Optional[uuid.UUID] = None
    lot_number: Optional[str] = None
    expiry_date: Optional[date] = None
    auto_lot: bool = False


class ApprovalInfoResponse(BaseModel):
    """Response for GET /transfers/{id}/approval-info.

    Session 6: when resolved_approval_steps are present (dynamic routing),
    can_approve is true only when the caller IS the specifically-assigned approver
    (or one of the all_holders list for ANY-mode steps).
    Legacy fields (required_authority_level etc.) preserved for backward compat.
    """
    transfer_id:              uuid.UUID
    required_authority_level: int
    required_role_display:    str
    is_auto_approve:          bool
    can_approve:              bool
    reason:                   str
    # Session 6 — specific assignee fields
    current_step:                    int           = 1
    total_steps:                     int           = 1
    current_approver_user_id:        Optional[str] = None
    current_approver_name:           Optional[str] = None
    current_approver_position_title: Optional[str] = None
    execution_mode:                  str           = "sequential"
    sla_hours:                       Optional[int] = None
    is_dynamic_routing:              bool          = False
    # ANY-mode and status-label fields
    holder_count:                    int           = 1
    all_holders:                     list[dict]    = []
    status_label:                    Optional[str] = None


class AdjustmentApprovalInfoResponse(BaseModel):
    """Response for GET /adjustments/{id}/approval-info.

    When a Design-B product override has routed the adjustment to a
    specific position/user, can_approve is gated on that resolved
    approver (or, if escalated, any active TA who isn't the creator).
    Adjustments without an override fall back to the normal
    adjustment:approve RBAC grant.
    """
    adjustment_id:             uuid.UUID
    status:                    str
    product_override_applied: bool           = False
    required_approver_user_id: Optional[uuid.UUID] = None
    required_approver_name:    Optional[str]      = None
    approver_escalated:        bool               = False
    can_approve:               bool
    step_label:                Optional[str]      = None
    lot_id:                    Optional[uuid.UUID] = None
    lot_number:                Optional[str]      = None
    expiry_date:               Optional[date]     = None
    auto_lot:                  bool               = False


class AuditLogItem(BaseModel):
    id: uuid.UUID
    timestamp: datetime
    user_id: Optional[uuid.UUID] = None
    user_name: Optional[str] = None
    role: Optional[str] = None
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[uuid.UUID] = None
    decision: str
    reason: Optional[str] = None
    abac_context: Optional[dict] = None
    transfer_type: Optional[str] = None
    from_warehouse_name: Optional[str] = None
    to_warehouse_name: Optional[str] = None
    product_summary: Optional[str] = None
    adjustment_reason_code: Optional[str] = None
