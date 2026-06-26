"""Plan-check middleware — enforces feature flags and resource
limits before RBAC/ABAC permission checks.

Raises HTTP 402 with structured error body when:
  - A feature flag required for the action is False
  - A resource count limit (warehouses, users, SKUs) is reached

Called from each service's dependency chain after tenant
resolution but before require_permission decorators.

Error body shape:
  {
    "code":       "FEATURE_NOT_IN_PLAN" | "PLAN_LIMIT_REACHED",
    "feature":    "<FLAG_NAME>",          # for FEATURE_NOT_IN_PLAN
    "resource":   "<warehouses|users|skus>",  # for PLAN_LIMIT_REACHED
    "plan_tier":  "<STARTER|GROWTH|ENTERPRISE>",
    "upgrade_to": "<GROWTH|ENTERPRISE>",   # next tier up, or null
  }
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# ── Feature flag gate map ─────────────────────────────────────────────────────
# Maps action strings (or action prefixes) to the feature flag that must be True.
# Actions not listed here are not feature-gated (always allowed if RBAC passes).

ACTION_FLAG_MAP: dict[str, str] = {
    "transfer:create_sister":   "TRANSFERS_SISTER",
    "transfer:sister":          "TRANSFERS_SISTER",
    "lot:":                     "LOT_TRACEABILITY",
    "batch:":                   "LOT_TRACEABILITY",
    "logistics:":               "LOGISTICS",
    "fleet:":                   "LOGISTICS",
    "audit:export":             "AUDIT_EXPORT",
    "branding:":                "CUSTOM_BRANDING",
    "analytics:ai":             "AI_ANALYTICS",
    "forecast:":                "AI_ANALYTICS",
    "api_access:":              "API_ACCESS",
}

# ── Upgrade path ──────────────────────────────────────────────────────────────
_UPGRADE_TO: dict[str, Optional[str]] = {
    "STARTER":    "GROWTH",
    "GROWTH":     "ENTERPRISE",
    "ENTERPRISE": None,
}


def _required_flag(action: str) -> Optional[str]:
    """Return the feature flag name required for this action, or None."""
    for prefix, flag in ACTION_FLAG_MAP.items():
        if action == prefix or action.startswith(prefix):
            return flag
    return None


async def _get_tenant_plan(
    db: AsyncSession, tenant_id: str
) -> dict[str, Any]:
    """Fetch plan_tier, feature_flags, sku_cap, max_warehouses, max_users."""
    row = (await db.execute(
        text(
            "SELECT plan_tier, feature_flags, sku_cap, "
            "       max_warehouses, max_users "
            "FROM   tenants WHERE id = :tid"
        ),
        {"tid": tenant_id},
    )).fetchone()
    if not row:
        return {}
    return {
        "plan_tier":      str(row.plan_tier) if row.plan_tier else "ENTERPRISE",
        "feature_flags":  dict(row.feature_flags) if row.feature_flags else {},
        "sku_cap":        row.sku_cap,
        "max_warehouses": row.max_warehouses,
        "max_users":      row.max_users,
    }


async def check_plan(
    user: Any,
    action: str,
    db: AsyncSession,
) -> None:
    """Raise HTTP 402 if the tenant's plan does not permit this action.

    SA and TA roles bypass plan checks entirely — they always have full
    access regardless of plan tier (SA manages plans, TA needs visibility).

    Skipped when user has no tenant_id (SA platform-level actions).
    """
    if not user or not getattr(user, "tenant_id", None):
        return
    if getattr(user, "role", "") in ("SA", "TA"):
        return

    tenant_id = str(user.tenant_id)
    plan = await _get_tenant_plan(db, tenant_id)
    if not plan:
        return  # tenant not found — let RBAC handle 404

    plan_tier     = plan["plan_tier"]
    feature_flags = plan["feature_flags"]
    upgrade_to    = _UPGRADE_TO.get(plan_tier)

    # ── Feature flag check ────────────────────────────────────────────────────
    required_flag = _required_flag(action)
    if required_flag is not None:
        if not feature_flags.get(required_flag, False):
            raise HTTPException(
                status_code=402,
                detail={
                    "code":       "FEATURE_NOT_IN_PLAN",
                    "feature":    required_flag,
                    "plan_tier":  plan_tier,
                    "upgrade_to": upgrade_to,
                    "message":    (
                        f"'{required_flag}' is not available on your current plan "
                        f"({plan_tier}). Upgrade to {upgrade_to or 'a higher tier'} "
                        f"to unlock this feature."
                    ),
                },
            )


async def check_plan_create_warehouse(
    user: Any,
    db: AsyncSession,
) -> None:
    """Raise HTTP 402 if the tenant has reached its sub-root node limit.

    The L1 (root) node is always free and is never counted.
    Only nodes at hierarchy_level > 1 count toward max_warehouses.

    Call this from create_org_node / reactivate_org_node for non-L1 nodes.
    Only SA bypasses this check — TA must stay within their tenant's plan limits.
    """
    if not user or not getattr(user, "tenant_id", None):
        return
    if getattr(user, "role", "") == "SA":
        return

    tenant_id = str(user.tenant_id)
    plan = await _get_tenant_plan(db, tenant_id)
    if not plan or plan.get("max_warehouses") is None:
        return  # unlimited

    # L1 nodes are the root/factory level and are free. Only sub-root nodes count.
    current = (await db.execute(
        text(
            "SELECT COUNT(*) FROM organization_node "
            "WHERE tenant_id = :tid AND is_active = true AND hierarchy_level > 1"
        ),
        {"tid": tenant_id},
    )).scalar() or 0

    if int(current) >= plan["max_warehouses"]:
        raise HTTPException(
            status_code=402,
            detail={
                "code":      "PLAN_LIMIT_REACHED",
                "resource":  "warehouses",
                "current":   int(current),
                "limit":     plan["max_warehouses"],
                "plan_tier": plan["plan_tier"],
                "upgrade_to": _UPGRADE_TO.get(plan["plan_tier"]),
                "message": (
                    f"Node limit reached ({current}/{plan['max_warehouses']}) "
                    f"for {plan['plan_tier']} plan. Upgrade to add more locations."
                ),
            },
        )


async def check_plan_create_user(
    user: Any,
    db: AsyncSession,
) -> None:
    """Raise HTTP 402 if the tenant has reached its user limit.

    Call this from create_user before inserting a new user.
    SA and TA bypass this check.
    """
    if not user or not getattr(user, "tenant_id", None):
        return
    if getattr(user, "role", "") in ("SA", "TA"):
        return

    tenant_id = str(user.tenant_id)
    plan = await _get_tenant_plan(db, tenant_id)
    if not plan or plan.get("max_users") is None:
        return  # unlimited

    current = (await db.execute(
        text(
            "SELECT COUNT(*) FROM users "
            "WHERE tenant_id = :tid AND is_active = true"
        ),
        {"tid": tenant_id},
    )).scalar() or 0

    if int(current) >= plan["max_users"]:
        raise HTTPException(
            status_code=402,
            detail={
                "code":      "PLAN_LIMIT_REACHED",
                "resource":  "users",
                "current":   int(current),
                "limit":     plan["max_users"],
                "plan_tier": plan["plan_tier"],
                "upgrade_to": _UPGRADE_TO.get(plan["plan_tier"]),
                "message": (
                    f"User limit reached ({current}/{plan['max_users']}) "
                    f"for {plan['plan_tier']} plan."
                ),
            },
        )
