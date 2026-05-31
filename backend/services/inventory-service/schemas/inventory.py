from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


class ReceiveStockRequest(BaseModel):
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    unit_cost: Optional[Decimal] = None
    lot_number: Optional[str] = None
    expiry_date: Optional[date] = None
    idempotency_key: str
    source: str = "WEB"


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
    notes: Optional[str] = None
    transfer_type_config_id: Optional[uuid.UUID] = None


class TransferLineRequest(BaseModel):
    product_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    lot_number: Optional[str] = None


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


class TransferActionRequest(BaseModel):
    notes: Optional[str] = None


class AdjustmentRequest(BaseModel):
    warehouse_id: uuid.UUID
    product_id: uuid.UUID
    quantity_delta: Decimal
    reason_code: str
    lot_number: Optional[str] = None
    idempotency_key: str
    notes: Optional[str] = None


class AdjustmentResponse(BaseModel):
    adjustment_id: uuid.UUID
    status: str
    quantity_delta: Decimal
    created_at: datetime


class CountSessionRequest(BaseModel):
    warehouse_id: uuid.UUID
    product_ids: Optional[List[uuid.UUID]] = None
    notes: Optional[str] = None


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
    reason_code: str
    notes: Optional[str] = None
    idempotency_key: str
    source: str = "WEB"
    override_zero_floor: bool = False


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
    lines: List[TransferLineItem]


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


class ApprovalInfoResponse(BaseModel):
    """Response for GET /transfers/{id}/approval-info.

    tells the caller who must approve this transfer, whether it auto-approves,
    and whether the current user has sufficient authority.
    """
    transfer_id:              uuid.UUID
    required_authority_level: int
    required_role_display:    str
    is_auto_approve:          bool
    can_approve:              bool
    reason:                   str
