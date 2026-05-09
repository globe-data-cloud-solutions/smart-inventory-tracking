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


class TenantCreateRequest(BaseModel):
    name: str
    plan_id: uuid.UUID
    default_locale: str = "en"


class TenantResponse(BaseModel):
    id: uuid.UUID
    name: str
    organisation_type: Optional[str]
    onboarding_complete: bool
    default_locale: str
    is_active: bool
