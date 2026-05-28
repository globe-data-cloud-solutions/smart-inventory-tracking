from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class ProductCreateRequest(BaseModel):
    """Request body for POST /api/v1/products.

    SKU is NOT accepted here — it is generated server-side via the atomic
    sku_counter UPDATE on the tenants table (SELECT FOR UPDATE).
    """

    name: str = Field(min_length=1, max_length=255)
    unit: str = Field(default="units", min_length=1, max_length=20)
    pack_size: int = Field(default=1, ge=1)
    category: Optional[str] = Field(default=None, max_length=255)
    reorder_point: Optional[Decimal] = Field(default=None, ge=0)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v

    @field_validator("unit", mode="before")
    @classmethod
    def strip_unit(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v

    @field_validator("category", mode="before")
    @classmethod
    def strip_category(cls, v: object) -> object:
        if isinstance(v, str):
            stripped = v.strip()
            return stripped if stripped else None
        return v


class CategoryCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v


class CategoryResponse(BaseModel):
    id: uuid.UUID
    name: str
    tenant_id: uuid.UUID


class ProductResponse(BaseModel):
    id: uuid.UUID
    sku: str
    name: str
    unit: str
    pack_size: int
    category: Optional[str] = None
    reorder_point: Optional[Decimal] = None
    tenant_id: uuid.UUID
    created_at: datetime
    created_by: Optional[uuid.UUID] = None


class NextSkuResponse(BaseModel):
    """Preview of the SKU that will be assigned on the next product creation.
    Does NOT increment sku_counter — this is a non-mutating read.
    """

    sku: str
    counter: Optional[int] = None
