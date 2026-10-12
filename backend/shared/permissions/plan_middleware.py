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

from shared.plans.catalog import get_tenant_entitlements
from shared.plans.usage import count_active_warehouses, count_billable_users

# ── Feature flag gate map ─────────────────────────────────────────────────────
# Maps action strings (or action prefixes) to the feature flag that must be True.
# Actions not listed here are not feature-gated (always allowed if RBAC passes).

ACTION_FLAG_MAP: dict[str, str] = {
    "transfer:sister":          "TRANSFERS_SISTER",   # kept for the explicit call in transfer.py
    "tenant:upload_branding":   "CUSTOM_BRANDING",
    "logistics:":               "LOGISTICS",
    "audit:export":             "AUDIT_EXPORT",
    "ai:":                      "AI_ANALYTICS",
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
    """Thin wrapper kept so callers don't change — delegates to
    shared.plans.catalog.get_tenant_entitlements(), the single source of a
    tenant's effective plan_tier, feature_flags, sku_cap, max_warehouses,
    max_users.
    """
    return await get_tenant_entitlements(db, tenant_id)


def requires_flag(action_id: str) -> bool:
    """True if this action is feature-gated (has an entry in ACTION_FLAG_MAP)."""
    return _required_flag(action_id) is not None


async def check_plan(
    user: Any,
    action: str,
    db: AsyncSession,
) -> None:
    """Raise HTTP 402 if the tenant's plan does not permit this action.

    Only SA bypasses plan checks — SA manages plans and always has full
    access regardless of plan tier. TA and all tenant users are gated like
    anyone else. Resource caps (warehouses/users) are unchanged.

    Skipped when user has no tenant_id (SA platform-level actions).
    """
    if not user or not getattr(user, "tenant_id", None):
        return
    if getattr(user, "role", "") == "SA":
        return

    tenant_id = str(user.tenant_id)
    plan = await _get_tenant_plan(db, tenant_id)
    if not plan:
        return  # tenant not found — let RBAC handle 404

    plan_tier     = plan["plan_tier"]
    feature_flags = plan["feature_flags"]
    upgrade_to    = _UPGRADE_TO.get(plan_tier)

    # ── Feature flag check ────────────────────────────────────────────────────
    # feature_flags.get(required_flag, False) denies by default: a flag that is
    # MISSING from the dict is treated exactly like an explicit False. This is
    # safe because migration 072 (S10) normalised every tenant's feature_flags
    # to carry every KNOWN_FEATURE_FLAGS key from its package, so "missing" no
    # longer happens in practice — but the deny-by-default code is intentional
    # defence in depth, not a gap: a tenant somehow missing a key must never be
    # silently granted a flag it was never assigned.
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
    """Raise HTTP 402 if the tenant has reached its warehouse limit.

    A "warehouse" is an active organization_node with is_stock_holding = true.
    Approval-only nodes (is_stock_holding = false) never count toward the cap,
    at any level. total_allowed = max_warehouses exactly — no free root slot.

    Call this only when the node being created/updated/reactivated will be
    stock-holding. Only SA bypasses.
    """
    if not user or not getattr(user, "tenant_id", None):
        return
    if getattr(user, "role", "") == "SA":
        return

    tenant_id = str(user.tenant_id)
    plan = await _get_tenant_plan(db, tenant_id)
    if not plan or plan.get("max_warehouses") is None:
        return  # unlimited

    # Lock the tenant row to serialize concurrent cap checks (prevents TOCTOU race
    # where two requests both pass the count check before either INSERT commits).
    await db.execute(
        text("SELECT id FROM tenants WHERE id = :tid FOR UPDATE"),
        {"tid": tenant_id},
    )

    current = await count_active_warehouses(db, tenant_id)

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
                    f"Warehouse limit reached ({current}/{plan['max_warehouses']} "
                    f"on the {plan['plan_tier']} plan). Approval-only locations "
                    f"(not holding stock) don't count."
                ),
            },
        )


async def check_plan_create_user(
    user: Any,
    db: AsyncSession,
) -> None:
    """Raise HTTP 402 if the tenant has reached its user limit.

    The Tenant Admin (TA) account is never counted toward the limit — it is the
    primary admin and always free. Only SA bypasses the check entirely.
    TA role users are now subject to the limit when creating non-TA accounts.
    """
    if not user or not getattr(user, "tenant_id", None):
        return
    if getattr(user, "role", "") == "SA":
        return

    tenant_id = str(user.tenant_id)
    plan = await _get_tenant_plan(db, tenant_id)
    if not plan or plan.get("max_users") is None:
        return  # unlimited

    # Lock the tenant row to serialize concurrent cap checks (prevents TOCTOU race
    # where two requests both pass the count check before either INSERT commits).
    await db.execute(
        text("SELECT id FROM tenants WHERE id = :tid FOR UPDATE"),
        {"tid": tenant_id},
    )

    # Exclude TA accounts from the count — the primary admin is always free.
    # IS DISTINCT FROM handles NULL correctly: regular users have system_role = NULL
    # and NULL != 'TA' is NULL in SQL (not TRUE), so != would silently exclude them.
    current = await count_billable_users(db, tenant_id)

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
