"""Package catalog — the single source of plan limits and feature flags.

platform_tier_config (migration 070) holds the package catalog: per-tier
max_warehouses, max_users, sku_cap and the full feature_flags set. A tenant
row holds its EFFECTIVE values, set by applying a package here. No tier
defaults are hardcoded anywhere else in the backend or frontend — every
caller that needs a package's limits or flags goes through this module.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class _Unset:
    def __repr__(self) -> str:  # pragma: no cover — debugging aid only
        return "UNSET"


# Sentinel distinguishing "caller did not pass this" (use the package's value)
# from an explicit override of None (which means "unlimited" for max_*/sku_cap).
UNSET: Any = _Unset()

# The complete, fixed set of feature flag codes a package's feature_flags dict may use.
# Single source of truth — SA package editing (PATCH /platform/tier-config) rejects any
# other key with 422 UNKNOWN_FEATURE_FLAG. Keep in sync with locales/en.json's
# tenant_admin.features.flag.* keys (frontend FeaturesTab.tsx FEATURE_MATRIX).
KNOWN_FEATURE_FLAGS: frozenset[str] = frozenset({
    "CORE_INVENTORY",
    "TRANSFERS_PULL_PUSH",
    "TRANSFERS_SISTER",
    "LOT_TRACEABILITY",
    "LOGISTICS",
    "AUDIT_EXPORT",
    "CUSTOM_BRANDING",
    "AI_ANALYTICS",
    "API_ACCESS",
})


def _row_to_package(row: Any) -> dict[str, Any]:
    return {
        "tier": row.tier,
        "display_name": row.display_name,
        "max_warehouses": row.max_warehouses,
        "max_users": row.max_users,
        "sku_cap": row.sku_cap,
        "feature_flags": dict(row.feature_flags) if row.feature_flags else {},
        "is_public": row.is_public,
        "sort_order": row.sort_order,
    }


async def get_package(db: AsyncSession, tier: str) -> dict[str, Any]:
    """Return the package catalog row for `tier`.

    Raises ValueError if the tier does not exist in platform_tier_config.
    There is no hardcoded fallback — the table is the only source.
    """
    row = (await db.execute(
        text(
            "SELECT tier, display_name, max_warehouses, max_users, sku_cap, "
            "       feature_flags, is_public, sort_order "
            "FROM platform_tier_config WHERE tier = :tier"
        ),
        {"tier": tier},
    )).fetchone()
    if not row:
        raise ValueError(f"Unknown plan tier: {tier}")
    return _row_to_package(row)


async def list_packages(db: AsyncSession, public_only: bool = False) -> list[dict[str, Any]]:
    """Return all package catalog rows, ordered by sort_order."""
    query = (
        "SELECT tier, display_name, max_warehouses, max_users, sku_cap, "
        "       feature_flags, is_public, sort_order "
        "FROM platform_tier_config "
    )
    if public_only:
        query += "WHERE is_public = true "
    query += "ORDER BY sort_order"
    rows = (await db.execute(text(query))).fetchall()
    return [_row_to_package(row) for row in rows]


async def apply_package_to_tenant(
    db: AsyncSession,
    tenant_id: str,
    tier: str,
    *,
    max_warehouses: Any = UNSET,
    max_users: Any = UNSET,
    sku_cap: Any = UNSET,
) -> dict[str, Any]:
    """Apply a package to a tenant: sets plan_tier, max_warehouses, max_users,
    sku_cap and REPLACES feature_flags with the package's full flag set.

    An explicit override (max_warehouses=, max_users=, sku_cap=) wins over the
    package's value for that field — including an explicit None, which means
    "unlimited". Omitted kwargs (the UNSET sentinel) take the package's value.

    Returns the effective values written. Single UPDATE statement.
    """
    package = await get_package(db, tier)

    effective_max_wh = package["max_warehouses"] if max_warehouses is UNSET else max_warehouses
    effective_max_u = package["max_users"] if max_users is UNSET else max_users
    effective_sku_cap = package["sku_cap"] if sku_cap is UNSET else sku_cap
    effective_flags = package["feature_flags"]

    await db.execute(
        text(
            "UPDATE tenants SET "
            "  plan_tier = CAST(:tier AS plan_tier), "
            "  max_warehouses = :max_wh, "
            "  max_users = :max_u, "
            "  sku_cap = :sku_cap, "
            "  feature_flags = CAST(:flags AS jsonb), "
            "  updated_at = now() "
            "WHERE id = :tid"
        ),
        {
            "tier": tier,
            "max_wh": effective_max_wh,
            "max_u": effective_max_u,
            "sku_cap": effective_sku_cap,
            "flags": json.dumps(effective_flags),
            "tid": str(tenant_id),
        },
    )
    return {
        "plan_tier": tier,
        "max_warehouses": effective_max_wh,
        "max_users": effective_max_u,
        "sku_cap": effective_sku_cap,
        "feature_flags": effective_flags,
    }


async def get_tenant_entitlements(db: AsyncSession, tenant_id: str) -> dict[str, Any]:
    """Return the tenant's EFFECTIVE plan values. This is the function all
    enforcement (check_plan, check_plan_create_user, check_plan_create_warehouse)
    reads — never the package catalog directly, since a tenant's values may
    have been overridden by SA past what its package assigns.
    """
    row = (await db.execute(
        text(
            "SELECT plan_tier, feature_flags, sku_cap, "
            "       max_warehouses, max_users "
            "FROM   tenants WHERE id = :tid"
        ),
        {"tid": str(tenant_id)},
    )).fetchone()
    if not row:
        return {}
    return {
        "plan_tier": str(row.plan_tier) if row.plan_tier else "ENTERPRISE",
        "feature_flags": dict(row.feature_flags) if row.feature_flags else {},
        "sku_cap": row.sku_cap,
        "max_warehouses": row.max_warehouses,
        "max_users": row.max_users,
    }
