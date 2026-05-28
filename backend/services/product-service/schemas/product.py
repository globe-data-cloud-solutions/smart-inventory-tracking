from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ── helpers ───────────────────────────────────────────────────────────────────

def _strip(v: object) -> object:
    return v.strip() if isinstance(v, str) else v

def _strip_opt(v: object) -> object:
    if isinstance(v, str):
        s = v.strip()
        return s if s else None
    return v


# ── product ───────────────────────────────────────────────────────────────────

class ProductCreateRequest(BaseModel):
    """POST /api/v1/products/ body.

    SKU is NOT accepted here — generated server-side via type_code + sequence count.
    sku_override bypasses generation and uses the supplied string (must be unique).
    """

    name: str = Field(min_length=1, max_length=255)
    short_name: Optional[str] = Field(default=None, max_length=50)
    description: Optional[str] = Field(default=None)
    category: Optional[str] = Field(default=None, max_length=255)
    type_code: str = Field(min_length=2, max_length=10,
                           description="Finds or creates a product_type_codes row")
    brand: Optional[str] = Field(default=None, max_length=100)
    unit: str = Field(default="units", min_length=1, max_length=50,
                      description="UOM string; finds or creates a product_uoms row")
    packaging_type: Optional[str] = Field(default=None, max_length=50)
    units_per_package: Optional[int] = Field(default=None, ge=1)
    reorder_point: Optional[Decimal] = Field(default=None, ge=0)
    sku_override: Optional[str] = Field(default=None, max_length=50,
                                        description="Manual SKU override; skips auto-generation")

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: object) -> object: return _strip(v)

    @field_validator("short_name", mode="before")
    @classmethod
    def strip_short_name(cls, v: object) -> object: return _strip_opt(v)

    @field_validator("description", mode="before")
    @classmethod
    def strip_desc(cls, v: object) -> object: return _strip_opt(v)

    @field_validator("category", mode="before")
    @classmethod
    def strip_category(cls, v: object) -> object: return _strip_opt(v)

    @field_validator("type_code", mode="before")
    @classmethod
    def upper_type_code(cls, v: object) -> object:
        return v.strip().upper() if isinstance(v, str) else v

    @field_validator("brand", mode="before")
    @classmethod
    def strip_brand(cls, v: object) -> object: return _strip_opt(v)

    @field_validator("unit", mode="before")
    @classmethod
    def strip_unit(cls, v: object) -> object: return _strip(v)

    @field_validator("packaging_type", mode="before")
    @classmethod
    def strip_pkg(cls, v: object) -> object: return _strip_opt(v)

    @field_validator("sku_override", mode="before")
    @classmethod
    def strip_sku_override(cls, v: object) -> object: return _strip_opt(v)


class ProductResponse(BaseModel):
    id: uuid.UUID
    sku: str
    name: str
    short_name: Optional[str] = None
    description: Optional[str] = None
    unit: str
    pack_size: int
    category: Optional[str] = None
    type_code: Optional[str] = None
    brand: Optional[str] = None
    packaging_type: Optional[str] = None
    units_per_package: Optional[int] = None
    reorder_point: Optional[Decimal] = None
    tenant_id: uuid.UUID
    created_at: datetime
    created_by: Optional[uuid.UUID] = None


# ── next-sku ──────────────────────────────────────────────────────────────────

class NextSkuResponse(BaseModel):
    """Preview of the SKU that will be assigned on the next product creation.
    Non-mutating — does NOT increment any counter.
    """

    sku: str
    counter: Optional[int] = None


# ── categories ────────────────────────────────────────────────────────────────

class CategoryCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: object) -> object: return _strip(v)


class CategoryResponse(BaseModel):
    id: uuid.UUID
    name: str
    tenant_id: uuid.UUID


# ── brands ────────────────────────────────────────────────────────────────────

class BrandCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: object) -> object: return _strip(v)


class BrandResponse(BaseModel):
    id: uuid.UUID
    name: str
    tenant_id: uuid.UUID


# ── type codes ────────────────────────────────────────────────────────────────

class TypeCodeCreateRequest(BaseModel):
    code: str = Field(min_length=2, max_length=10)
    description: Optional[str] = Field(default=None, max_length=100)

    @field_validator("code", mode="before")
    @classmethod
    def upper_code(cls, v: object) -> object:
        return v.strip().upper() if isinstance(v, str) else v

    @field_validator("description", mode="before")
    @classmethod
    def strip_desc(cls, v: object) -> object: return _strip_opt(v)


class TypeCodeResponse(BaseModel):
    id: uuid.UUID
    code: str
    description: Optional[str] = None
    tenant_id: uuid.UUID


# ── UOMs ──────────────────────────────────────────────────────────────────────

class UomCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=50)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: object) -> object: return _strip(v)


class UomResponse(BaseModel):
    id: uuid.UUID
    name: str
    tenant_id: uuid.UUID


# ── packaging types ───────────────────────────────────────────────────────────

class PackagingTypeCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    units_per_package: int = Field(default=1, ge=1)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: object) -> object: return _strip(v)


class PackagingTypeResponse(BaseModel):
    id: uuid.UUID
    name: str
    units_per_package: int
    tenant_id: uuid.UUID
