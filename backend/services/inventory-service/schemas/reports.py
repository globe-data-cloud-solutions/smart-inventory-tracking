from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


class ValuationRow(BaseModel):
    product_id: uuid.UUID
    sku: str
    name: str
    warehouse_id: uuid.UUID
    warehouse_name: Optional[str] = None
    on_hand: Decimal
    unit_cost: Decimal
    total_value: Decimal


class MovementRow(BaseModel):
    transaction_id: uuid.UUID
    transaction_date: date
    type: str
    product_id: uuid.UUID
    sku: str
    name: str
    warehouse_id: uuid.UUID
    warehouse_name: Optional[str] = None
    quantity: Decimal
    unit_cost: Optional[Decimal] = None
    lot_number: Optional[str] = None
    created_at: datetime


class ExpiryAlertRow(BaseModel):
    product_id: uuid.UUID
    sku: str
    name: str
    warehouse_id: uuid.UUID
    warehouse_name: Optional[str] = None
    lot_number: Optional[str] = None
    expiry_date: date
    quantity: Decimal
    days_to_expiry: int


class LevelOption(BaseModel):
    level_number: int
    level_name: str


class NodeOption(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    hierarchy_level: int
    parent_node_id: Optional[uuid.UUID] = None


class ReportFilterOptions(BaseModel):
    levels: list[LevelOption]
    nodes: list[NodeOption]


class DispatchRow(BaseModel):
    """One product on one dispatch (transfer order). A dispatch is in scope when
    its source or its destination warehouse is in the caller's scope."""

    transfer_order_id: uuid.UUID
    dispatched_on: date
    from_warehouse_id: uuid.UUID
    from_warehouse_name: Optional[str] = None
    to_warehouse_id: uuid.UUID
    to_warehouse_name: Optional[str] = None
    product_id: uuid.UUID
    sku: str
    name: str
    quantity_dispatched: Decimal
    lots_used: int
    overrides: int


class LotHeader(BaseModel):
    lot_number: str
    product_id: uuid.UUID
    sku: str
    name: str
    expiry_date: Optional[date] = None
    first_received_at: datetime


class LotBalanceRow(BaseModel):
    warehouse_id: uuid.UUID
    warehouse_name: Optional[str] = None
    quantity: Decimal


class LotHistoryRow(BaseModel):
    transaction_id: uuid.UUID
    transaction_date: date
    type: str
    warehouse_id: uuid.UUID
    warehouse_name: Optional[str] = None
    quantity: Decimal
    created_at: datetime


class LotTraceOut(BaseModel):
    lot: LotHeader
    balances: list[LotBalanceRow]
    history: list[LotHistoryRow]
