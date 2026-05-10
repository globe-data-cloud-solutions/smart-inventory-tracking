from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ProductCreateRequest(BaseModel):
    """Request body for POST /api/v1/products.

    SKU is NOT accepted here — it is generated server-side via the atomic
    sku_counter UPDATE on the tenants table (SELECT FOR UPDATE).
    """

    name: str = Field(min_length=1, max_length=255, strip_whitespace=True)
    unit: Literal["KG", "PACK", "QTL", "MT"]
    pack_size: Literal[1, 4, 6, 12]


class ProductResponse(BaseModel):
    id: uuid.UUID
    sku: str
    name: str
    unit: str
    pack_size: int
    tenant_id: uuid.UUID
    created_at: datetime
    created_by: Optional[uuid.UUID] = None


class NextSkuResponse(BaseModel):
    """Preview of the SKU that will be assigned on the next product creation.
    Does NOT increment sku_counter — this is a non-mutating read.
    """

    sku: str
