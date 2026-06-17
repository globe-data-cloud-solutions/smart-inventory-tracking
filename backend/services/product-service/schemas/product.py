from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ── helpers ───────────────────────────────────────────────────────────────────

def _strip(v: object) -> object:
    if isinstance(v, str):
        if '\x00' in v:
            raise ValueError("Null bytes are not allowed in text fields")
        return v.strip()
    return v

def _strip_opt(v: object) -> object:
    if isinstance(v, str):
        if '\x00' in v:
            raise ValueError("Null bytes are not allowed in text fields")
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
    unit_price: Optional[Decimal] = Field(default=None, ge=0,
                                          description="Unit selling/transfer price; used for total_value on transfers")
    currency: str = Field(default="ETB", max_length=10)

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


class ProductUpdateRequest(BaseModel):
    """PATCH /api/v1/products/{product_id} body.

    All fields optional — only supplied (non-None) fields are updated.
    SKU is never editable here; it is fixed at creation time.
    """

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    short_name: Optional[str] = Field(default=None, max_length=50)
    description: Optional[str] = Field(default=None)
    category: Optional[str] = Field(default=None, max_length=255)
    type_code: Optional[str] = Field(default=None, min_length=2, max_length=10)
    brand: Optional[str] = Field(default=None, max_length=100)
    unit: Optional[str] = Field(default=None, min_length=1, max_length=50)
    packaging_type: Optional[str] = Field(default=None, max_length=50)
    units_per_package: Optional[int] = Field(default=None, ge=1)
    reorder_point: Optional[Decimal] = Field(default=None, ge=0)
    unit_price: Optional[Decimal] = Field(default=None, ge=0)
    currency: Optional[str] = Field(default=None, max_length=10)
    image_url: Optional[str] = Field(default=None)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: object) -> object: return _strip_opt(v)

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
    def strip_unit(cls, v: object) -> object: return _strip_opt(v)

    @field_validator("packaging_type", mode="before")
    @classmethod
    def strip_pkg(cls, v: object) -> object: return _strip_opt(v)


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
    unit_price: Optional[Decimal] = None
    currency: Optional[str] = None
    image_url: Optional[str] = None
    is_controlled: bool = False
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


# ── approval rules ────────────────────────────────────────────────────────────

_VALID_TX_TYPES   = {"PULL", "PUSH", "ADJUSTMENT", "SISTER"}
_VALID_APPROVERS  = {"WM", "RM", "NM", "TA", "SA"}


class ApprovalRuleEntry(BaseModel):
    """One quantity band override for a specific product + transaction type."""

    transaction_type: str = Field(description="PULL | PUSH | ADJUSTMENT | SISTER")
    min_quantity:     Optional[Decimal] = Field(default=None, ge=0)
    max_quantity:     Optional[Decimal] = Field(default=None, ge=0)
    approver_role:    str = Field(min_length=2, max_length=10)
    approval_order:   int = Field(default=1, ge=1)

    @field_validator("transaction_type", mode="before")
    @classmethod
    def validate_tx_type(cls, v: object) -> object:
        if isinstance(v, str) and v.upper() in _VALID_TX_TYPES:
            return v.upper()
        raise ValueError(f"transaction_type must be one of {sorted(_VALID_TX_TYPES)}")

    @field_validator("approver_role", mode="before")
    @classmethod
    def validate_role(cls, v: object) -> object:
        if isinstance(v, str) and v.upper() in _VALID_APPROVERS:
            return v.upper()
        raise ValueError(f"approver_role must be one of {sorted(_VALID_APPROVERS)}")


class ApprovalRulesUpsertRequest(BaseModel):
    """PUT /api/v1/products/{product_id}/approval-rules body.

    Send an empty list to reset to tenant defaults (clears all product-level rules).
    """
    rules: list[ApprovalRuleEntry] = Field(default_factory=list)


class ApprovalRuleResponse(BaseModel):
    """Single row from the approval_rule table, annotated with scope."""

    id:               uuid.UUID
    transaction_type: str
    min_quantity:     Optional[Decimal] = None
    max_quantity:     Optional[Decimal] = None
    approver_role:    str
    approval_order:   int
    product_id:       Optional[uuid.UUID] = None
    is_product_level: bool  # True when product_id is set


class ProductApprovalRulesResponse(BaseModel):
    """Response from GET /products/{id}/approval-rules and /approval-rules/latest."""

    product_id:        Optional[uuid.UUID] = None
    rules:             list[ApprovalRuleResponse]
    is_using_defaults: bool  # True when product has no custom rules of its own


# ── product approval minimums ─────────────────────────────────────────────────

_VALID_MIN_TX_TYPES = {"PULL", "PUSH", "ADJUSTMENT", "SISTER", "RECEIVE", "ISSUE"}
_VALID_THRESHOLD_TYPES = {"ALWAYS", "QUANTITY", "VALUE"}


class ApprovalMinimumEntry(BaseModel):
    """One per-product, per-transaction-type approval configuration row.

    Combines two independent mechanisms that share the same
    product_approval_minimums row (CLAUDE.md migration 050):

      - min_authority_level: authority-floor override (legacy, unchanged).
        None deletes/omits the authority floor for this tx_type.
      - override_enabled + threshold_type/qty_threshold/value_threshold/
        approver_position_id/note: Design-B precedence override consulted by
        check_product_override(). override_enabled=False means no Design-B
        override is configured for this tx_type.

    A row is persisted only if min_authority_level is not None OR
    override_enabled is True; otherwise any existing row for this tx_type
    is deleted.
    """
    transaction_type:     str
    min_authority_level:  Optional[int] = Field(default=None, ge=1, le=5)
    override_enabled:     bool = False
    threshold_type:       str = "ALWAYS"
    qty_threshold:        Optional[Decimal] = Field(default=None, ge=0)
    value_threshold:      Optional[Decimal] = Field(default=None, ge=0)
    approver_position_id: Optional[uuid.UUID] = None
    note:                 Optional[str] = None

    @field_validator("transaction_type", mode="before")
    @classmethod
    def validate_tx_type(cls, v: object) -> object:
        if isinstance(v, str) and v.upper() in _VALID_MIN_TX_TYPES:
            return v.upper()
        raise ValueError(f"transaction_type must be one of {sorted(_VALID_MIN_TX_TYPES)}")

    @field_validator("threshold_type", mode="before")
    @classmethod
    def validate_threshold_type(cls, v: object) -> object:
        if isinstance(v, str) and v.upper() in _VALID_THRESHOLD_TYPES:
            return v.upper()
        raise ValueError(f"threshold_type must be one of {sorted(_VALID_THRESHOLD_TYPES)}")


class ApprovalMinimumsUpsertRequest(BaseModel):
    """PUT /products/{product_id}/approval-minimums body.

    entries must be non-empty unless clear_all=true — this prevents a
    malformed or wrongly-shaped body from silently wiping all existing
    overrides via the default empty list.

    To intentionally clear all product-level approval configuration,
    set clear_all=true (entries may be empty or omitted in that case).
    """
    entries: list[ApprovalMinimumEntry] = Field(default_factory=list)
    clear_all: bool = False


class ApprovalMinimumResponse(BaseModel):
    """One row from product_approval_minimums."""
    id:                   uuid.UUID
    product_id:           uuid.UUID
    transaction_type:     str
    min_authority_level:  Optional[int] = None
    override_enabled:     bool = False
    threshold_type:       str = "ALWAYS"
    qty_threshold:        Optional[Decimal] = None
    value_threshold:      Optional[Decimal] = None
    approver_position_id: Optional[uuid.UUID] = None
    approver_label:       Optional[str] = None
    note:                 Optional[str] = None
    created_by:           uuid.UUID
    created_at:           datetime
    updated_at:           datetime


class ProductApprovalMinimumsResponse(BaseModel):
    """Response from GET/PUT /products/{id}/approval-minimums."""
    product_id: uuid.UUID
    minimums:   list[ApprovalMinimumResponse]


class ProductApprovalOverride(BaseModel):
    """Computed Design-B override summary for one transaction type.

    Included in GET /products/ list responses as `approval_overrides`,
    keyed by transaction_type. Consumed by NewTransferPanel /
    NewAdjustmentPanel (PART F) to render the lock icon + tooltip.
    """
    mode:           str  # ALWAYS | QUANTITY | VALUE
    threshold:      Optional[Decimal] = None
    approver_label: Optional[str] = None
    note:           Optional[str] = None
