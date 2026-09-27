from __future__ import annotations

import uuid
from typing import Dict, Optional

from pydantic import BaseModel


class WizardData(BaseModel):
    org_type: str  # PRODUCER | RETAILER | HYBRID
    default_locale: str = "en"
    sku_limit: Optional[int] = None


class WizardResult(BaseModel):
    tenant_id: str
    org_type: str
    feature_flags: Dict[str, bool]
    onboarding_complete: bool
    plan_tier: str = "GROWTH"


DEFAULT_SYSTEM_PLAN_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


VALID_PLAN_TIERS = {"STARTER", "GROWTH", "ENTERPRISE"}
VALID_LOCALES = {"en", "am", "or"}


class TenantCreateRequest(BaseModel):
    name: str
    slug: Optional[str] = None               # custom URL identifier; auto-generated if omitted
    plan_id: Optional[uuid.UUID] = DEFAULT_SYSTEM_PLAN_ID
    default_locale: str = "en"
    # tenants.organisation_type is NOT NULL at the DB level (it's a PostgreSQL
    # ENUM column) — defaulting here keeps the field optional from the caller's
    # perspective without risking a NotNullViolationError on INSERT. Validity
    # (PRODUCER | RETAILER | HYBRID) is checked in the route handler, where it
    # can raise the structured 422 INVALID_ORGANISATION_TYPE error this codebase
    # uses elsewhere, rather than Pydantic's generic validation-error shape.
    organisation_type: str = "PRODUCER"
    plan_tier: str = "GROWTH"
    # PRODUCER-only: maximum active SKUs allowed. NULL = unlimited (RETAILER/HYBRID).
    sku_cap: Optional[int] = None
    industry: Optional[str] = None
    # Optional atomic TA admin user creation
    admin_name: Optional[str] = None
    admin_email: Optional[str] = None
    admin_password: Optional[str] = None


class TenantResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: Optional[str] = None
    organisation_type: Optional[str]
    onboarding_complete: bool
    default_locale: str
    is_active: bool
    status: Optional[str] = None
    logo_url: Optional[str] = None
    banner_url: Optional[str] = None
    plan_tier: Optional[str] = None
    max_warehouses: Optional[int] = None
    max_users: Optional[int] = None
    # Contract dates — readable by TA (read-only); editable only by SA via PATCH /contract
    contract_start: Optional[str] = None
    contract_end: Optional[str] = None
    # Populated when admin user was created atomically
    admin_user_id: Optional[uuid.UUID] = None
    admin_email: Optional[str] = None
