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
    quantity: Decimal
    unit_cost: Optional[Decimal] = None
    lot_number: Optional[str] = None
    created_at: datetime


class ExpiryAlertRow(BaseModel):
    product_id: uuid.UUID
    sku: str
    name: str
    warehouse_id: uuid.UUID
    lot_number: Optional[str] = None
    expiry_date: date
    quantity: Decimal
    days_to_expiry: int
