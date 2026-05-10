from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class BasePayload(BaseModel):
    version: str = "1.0"


class InventoryUpdatedPayload(BasePayload):
    event_type: Literal["InventoryUpdated"] = "InventoryUpdated"
    product_id: str
    warehouse_id: str
    delta: float
    transaction_id: str


class StockTransferredPayload(BasePayload):
    event_type: Literal["StockTransferred"] = "StockTransferred"
    from_warehouse_id: str
    to_warehouse_id: str
    product_id: str
    quantity: float
    transfer_order_id: str


class OrderCreatedPayload(BasePayload):
    event_type: Literal["OrderCreated"] = "OrderCreated"
    order_id: str
    customer_id: str
    line_count: int


class ShipmentDispatchedPayload(BasePayload):
    event_type: Literal["ShipmentDispatched"] = "ShipmentDispatched"
    shipment_id: str
    order_id: str
    warehouse_id: str


class AdjustmentAppliedPayload(BasePayload):
    event_type: Literal["AdjustmentApplied"] = "AdjustmentApplied"
    adjustment_id: str
    product_id: str
    warehouse_id: str
    delta: float


class StockCountCompletedPayload(BasePayload):
    event_type: Literal["StockCountCompleted"] = "StockCountCompleted"
    count_session_id: str
    warehouse_id: str
    variance_count: int


class TenantOrgTypeChangedPayload(BasePayload):
    event_type: Literal["TenantOrgTypeChanged"] = "TenantOrgTypeChanged"
    from_type: str | None
    to_type: str
    changed_by: str


class FefoOverrideAppliedPayload(BasePayload):
    event_type: Literal["FefoOverrideApplied"] = "FefoOverrideApplied"
    override_log_id: str
    product_id: str
    lot_id: str
    reason_code: str


class TransferRequestedPayload(BasePayload):
    """Notifies the source warehouse that a pull request has been submitted.
    Written to the outbox in the same transaction as the transfer_request row.
    Delivered by the notification worker to the source warehouse's alert feed.
    """
    event_type: Literal["TransferRequested"] = "TransferRequested"
    transfer_request_id: str
    requesting_warehouse_id: str
    requesting_warehouse_name: str
    source_warehouse_id: str
    product_id: str
    product_name: str
    quantity: float
    required_date: str | None = None


PAYLOAD_TYPES = {
    "InventoryUpdated": InventoryUpdatedPayload,
    "StockTransferred": StockTransferredPayload,
    "OrderCreated": OrderCreatedPayload,
    "ShipmentDispatched": ShipmentDispatchedPayload,
    "AdjustmentApplied": AdjustmentAppliedPayload,
    "StockCountCompleted": StockCountCompletedPayload,
    "TenantOrgTypeChanged": TenantOrgTypeChangedPayload,
    "FefoOverrideApplied": FefoOverrideAppliedPayload,
    "TransferRequested":   TransferRequestedPayload,
}
