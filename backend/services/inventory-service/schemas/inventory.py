from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


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


class ReceiveStockRequest(BaseModel):
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    unit_cost: Optional[Decimal] = None
    lot_number: Optional[str] = None
    expiry_date: Optional[date] = None
    idempotency_key: str
    source: str = "WEB"

    @field_validator("lot_number", "idempotency_key", "source", mode="before")
    @classmethod
    def no_null_bytes(cls, v: object) -> object: return _no_null(v)


class ReceiveStockResponse(BaseModel):
    transaction_id: uuid.UUID
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    quantity: Decimal
    created_at: datetime


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


class TransferOrderResponse(BaseModel):
    transfer_id: uuid.UUID
    transfer_type: str
    status: str
    from_warehouse_id: uuid.UUID
    to_warehouse_id: uuid.UUID
    created_at: datetime
    total_value: Optional[Decimal] = None
    currency: Optional[str] = None
    transfer_type_config_id: Optional[uuid.UUID] = None
    is_self_approved: bool = False
    current_approval_step: Optional[int] = None
    resolved_approval_steps: Optional[list] = None


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
    lot_number: Optional[str] = None
    idempotency_key: str
    notes: Optional[str] = Field(None, max_length=2000)

    @field_validator("lot_number", "idempotency_key", "notes", mode="before")
    @classmethod
    def no_null_bytes(cls, v: object) -> object: return _no_null(v)


class AdjustmentResponse(BaseModel):
    adjustment_id: uuid.UUID
    status: str
    quantity_delta: Decimal
    created_at: datetime
    is_self_approved: bool = False
    total_value: Optional[Decimal] = None


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

    @field_validator("reason_code", "issued_to", "notes", "idempotency_key", "source", mode="before")
    @classmethod
    def no_null_bytes(cls, v: object) -> object: return _no_null(v)


class IssueStockResponse(BaseModel):
    transaction_id: uuid.UUID
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    quantity: Decimal
    reason_code: str
    created_at: datetime


class LotSelection(BaseModel):
    lot_id: uuid.UUID
    lot_number: Optional[str]
    quantity: Decimal
    strategy_applied: str


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

class TransferLineItem(BaseModel):
    product_id: uuid.UUID
    product_name: str
    sku: str
    quantity: Decimal
    uom: str


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
