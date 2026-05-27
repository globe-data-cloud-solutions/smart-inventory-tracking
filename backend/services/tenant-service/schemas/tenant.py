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


DEFAULT_SYSTEM_PLAN_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class TenantCreateRequest(BaseModel):
    name: str
    plan_id: Optional[uuid.UUID] = DEFAULT_SYSTEM_PLAN_ID
    default_locale: str = "en"
    organisation_type: Optional[str] = None   # PRODUCER | RETAILER | HYBRID


class TenantResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: Optional[str] = None
    organisation_type: Optional[str]
    onboarding_complete: bool
    default_locale: str
    is_active: bool
