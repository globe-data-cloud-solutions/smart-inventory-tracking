from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.outbox.schemas import TenantOrgTypeChangedPayload
from shared.outbox.writer import write_to_outbox
from services.tenant_service.schemas.tenant import WizardData, WizardResult

FEATURE_FLAG_DEFAULTS: dict[str, dict[str, bool]] = {
    "PRODUCER": {
        "LOGISTICS": False,
        "AI_ANALYTICS": False,
        "ADVANCED_BATCH_TRACKING": True,
        "FLEET_MANAGEMENT": False,
    },
    "RETAILER": {
        "LOGISTICS": True,
        "AI_ANALYTICS": True,
        "ADVANCED_BATCH_TRACKING": False,
        "FLEET_MANAGEMENT": True,
    },
    "HYBRID": {
        "LOGISTICS": True,
        "AI_ANALYTICS": True,
        "ADVANCED_BATCH_TRACKING": True,
        "FLEET_MANAGEMENT": True,
    },
}

APPROVAL_DEFAULTS: dict[str, dict] = {
    "PRODUCER": {"inventory:adjust": {"low": 100, "medium": 500}},
    "RETAILER": {"inventory:adjust": {"low": 500, "medium": 5000}},
    "HYBRID":   {"inventory:adjust": {"low": 250, "medium": 2000}},
}


async def complete_wizard(
    db: AsyncSession, tenant_id: str, data: WizardData, changed_by: str
) -> WizardResult:
    import json

    feature_flags = FEATURE_FLAG_DEFAULTS[data.org_type]
    approval_thresholds = APPROVAL_DEFAULTS[data.org_type]

    await db.execute(
        text(
            "UPDATE tenants SET "
            "  organisation_type   = :org_type, "
            "  feature_flags       = :flags::jsonb, "
            "  approval_thresholds = :thresholds::jsonb, "
            "  default_locale      = :locale, "
            "  onboarding_complete = true, "
            "  updated_at          = now() "
            "WHERE id = :tid"
        ),
        {
            "org_type": data.org_type,
            "flags": json.dumps(feature_flags),
            "thresholds": json.dumps(approval_thresholds),
            "locale": data.default_locale,
            "tid": tenant_id,
        },
    )

    if data.org_type == "PRODUCER" and data.sku_limit:
        await db.execute(
            text("UPDATE tenants SET sku_cap = :cap WHERE id = :tid"),
            {"cap": data.sku_limit, "tid": tenant_id},
        )

    # Outbox in SAME transaction
    await write_to_outbox(
        db,
        tenant_id,
        "TenantOrgTypeChanged",
        TenantOrgTypeChangedPayload(
            from_type=None,
            to_type=data.org_type,
            changed_by=changed_by,
        ),
    )

    return WizardResult(
        tenant_id=tenant_id,
        org_type=data.org_type,
        feature_flags=feature_flags,
        onboarding_complete=True,
    )
