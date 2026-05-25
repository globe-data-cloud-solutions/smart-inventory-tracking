from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, computed_field


class InventoryStockOut(BaseModel):
    product_id: uuid.UUID
    product_name: str
    product_sku: str
    warehouse_id: uuid.UUID
    warehouse_name: str
    warehouse_type: Optional[str] = None
    current_stock: Decimal
    pending_out_qty: Decimal = Decimal("0")     # approved/in-transit going out
    in_transit_in_qty: Decimal = Decimal("0")   # inbound not yet received
    requested_qty: Decimal = Decimal("0")        # pending transfer requests on this stock

    @computed_field  # type: ignore[misc]
    @property
    def net_available(self) -> Decimal:
        """Conservatively available: current minus all committed outbound."""
        return self.current_stock - self.pending_out_qty - self.requested_qty


class ReorderAlertOut(BaseModel):
    product_id: uuid.UUID
    product_name: str
    product_sku: str
    warehouse_id: uuid.UUID
    warehouse_name: str
    current_stock: Decimal
    reorder_point: Decimal
    reorder_quantity: Optional[Decimal] = None
    shortfall: Decimal   # reorder_point - current_stock (always > 0 in alerts)


class ForecastOut(BaseModel):
    product_id: uuid.UUID
    product_name: str
    product_sku: str
    warehouse_id: uuid.UUID
    warehouse_name: str
    current_stock: Decimal
    avg_daily_consumption: float
    days_until_stockout: Optional[float] = None   # None = no consumption in window


class CrossWarehouseStockOut(BaseModel):
    product_id: uuid.UUID
    product_name: str
    product_sku: str
    total_stock: Decimal
    warehouses: List[InventoryStockOut]


class TransferHistoryItem(BaseModel):
    transfer_id: uuid.UUID
    reference_number: Optional[str] = None
    destination_warehouse_id: uuid.UUID
    destination_warehouse_name: str
    quantity: Decimal
    status: str
    created_at: datetime


class TransferRequestOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    requesting_warehouse_id: uuid.UUID
    requesting_warehouse_name: str
    source_warehouse_id: uuid.UUID
    source_warehouse_name: str
    product_id: uuid.UUID
    product_name: str
    product_sku: str
    quantity: Decimal
    required_date: Optional[date] = None
    notes: Optional[str] = None
    status: str
    created_at: datetime


class TransferRequestCreate(BaseModel):
    requesting_warehouse_id: uuid.UUID
    source_warehouse_id: uuid.UUID
    product_id: uuid.UUID
    quantity: Decimal
    required_date: Optional[date] = None
    notes: Optional[str] = None


class WarehouseOut(BaseModel):
    id: uuid.UUID
    name: str
    warehouse_type: Optional[str] = None
    address: Optional[str] = None
    manager_name: Optional[str] = None
