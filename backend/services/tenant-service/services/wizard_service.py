from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.outbox.schemas import TenantOrgTypeChangedPayload
from shared.outbox.writer import write_to_outbox
from schemas.tenant import WizardData, WizardResult

APPROVAL_DEFAULTS: dict[str, dict] = {
    "PRODUCER": {"inventory:adjust": {"low": 100, "medium": 500}},
    "RETAILER": {"inventory:adjust": {"low": 500, "medium": 5000}},
    "HYBRID": {"inventory:adjust": {"low": 250, "medium": 2000}},
}


async def complete_wizard(
    db: AsyncSession, tenant_id: str, data: WizardData, changed_by: str
) -> WizardResult:
    import json

    approval_thresholds = APPROVAL_DEFAULTS[data.org_type]

    # Wizard sets org type, approval thresholds and locale only — no plan,
    # no flags. Those are owned by the package catalog (CLAUDE.md §15) and
    # are set when the tenant is created (apply_package_to_tenant), not here.
    await db.execute(
        text(
            "UPDATE tenants SET "
            "  organisation_type   = :org_type, "
            "  approval_thresholds = CAST(:thresholds AS jsonb), "
            "  default_locale      = :locale, "
            "  onboarding_complete = true, "
            "  updated_at          = now() "
            "WHERE id = :tid"
        ),
        {
            "org_type": data.org_type,
            "thresholds": json.dumps(approval_thresholds),
            "locale": data.default_locale,
            "tid": tenant_id,
        },
    )

    if data.sku_limit:
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

    current = (
        await db.execute(
            text("SELECT feature_flags, plan_tier FROM tenants WHERE id = :tid"),
            {"tid": tenant_id},
        )
    ).fetchone()

    return WizardResult(
        tenant_id=tenant_id,
        org_type=data.org_type,
        feature_flags=dict(current.feature_flags) if current and current.feature_flags else {},
        onboarding_complete=True,
        plan_tier=str(current.plan_tier) if current and current.plan_tier else "GROWTH",
    )
