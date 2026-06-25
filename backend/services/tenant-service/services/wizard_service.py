from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.outbox.schemas import TenantOrgTypeChangedPayload
from shared.outbox.writer import write_to_outbox
from schemas.tenant import WizardData, WizardResult

FEATURE_FLAG_DEFAULTS: dict[str, dict[str, bool]] = {
    "PRODUCER": {
        "CORE_INVENTORY":      True,
        "TRANSFERS_PULL_PUSH": True,
        "TRANSFERS_SISTER":    False,
        "LOT_TRACEABILITY":    True,
        "LOGISTICS":           False,
        "AUDIT_EXPORT":        False,
        "CUSTOM_BRANDING":     False,
        "AI_ANALYTICS":        False,
        "API_ACCESS":          False,
    },
    "RETAILER": {
        "CORE_INVENTORY":      True,
        "TRANSFERS_PULL_PUSH": True,
        "TRANSFERS_SISTER":    True,
        "LOT_TRACEABILITY":    False,
        "LOGISTICS":           True,
        "AUDIT_EXPORT":        True,
        "CUSTOM_BRANDING":     True,
        "AI_ANALYTICS":        True,
        "API_ACCESS":          False,
    },
    "HYBRID": {
        "CORE_INVENTORY":      True,
        "TRANSFERS_PULL_PUSH": True,
        "TRANSFERS_SISTER":    True,
        "LOT_TRACEABILITY":    True,
        "LOGISTICS":           True,
        "AUDIT_EXPORT":        True,
        "CUSTOM_BRANDING":     True,
        "AI_ANALYTICS":        True,
        "API_ACCESS":          False,
    },
}

TIER_DEFAULTS: dict[str, dict] = {
    "PRODUCER": {"plan_tier": "GROWTH",     "max_warehouses": 30,   "max_users": 50},
    "RETAILER": {"plan_tier": "GROWTH",     "max_warehouses": 30,   "max_users": 50},
    "HYBRID":   {"plan_tier": "ENTERPRISE", "max_warehouses": None, "max_users": None},
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
            "  feature_flags       = CAST(:flags AS jsonb), "
            "  approval_thresholds = CAST(:thresholds AS jsonb), "
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

    tier_defaults = TIER_DEFAULTS[data.org_type]
    await db.execute(
        text(
            "UPDATE tenants SET "
            "  plan_tier      = CAST(:tier AS plan_tier), "
            "  max_warehouses = :max_wh, "
            "  max_users      = :max_u, "
            "  updated_at     = now() "
            "WHERE id = :tid"
        ),
        {
            "tier": tier_defaults["plan_tier"],
            "max_wh": tier_defaults["max_warehouses"],
            "max_u":  tier_defaults["max_users"],
            "tid":    tenant_id,
        },
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
        plan_tier=tier_defaults["plan_tier"],
    )
