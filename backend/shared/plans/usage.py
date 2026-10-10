"""Shared resource-usage counts for plan enforcement and display.

Each count_* function here is the single source for how that resource is
counted toward its plan cap — plan_middleware.py's check_plan_create_user /
check_plan_create_warehouse and product-service's SKU cap check must all
read these instead of duplicating the SQL, so the enforcement count and the
displayed usage (GET /me/plan-usage) never drift apart.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.plans.catalog import get_tenant_entitlements


async def count_active_skus(db: AsyncSession, tenant_id: str) -> int:
    """Active products for this tenant — the same count product-service's
    create_product cap check uses."""
    result = await db.execute(
        text("SELECT COUNT(*) FROM products WHERE tenant_id = :tid AND is_active = true"),
        {"tid": str(tenant_id)},
    )
    return int(result.scalar() or 0)


async def count_billable_users(db: AsyncSession, tenant_id: str) -> int:
    """Active non-TA users — the exact count check_plan_create_user enforces
    against max_users (the TA account is always free)."""
    result = await db.execute(
        text(
            "SELECT COUNT(*) FROM users "
            "WHERE tenant_id = :tid AND is_active = true "
            "AND system_role IS DISTINCT FROM 'TA'"
        ),
        {"tid": str(tenant_id)},
    )
    return int(result.scalar() or 0)


async def count_active_warehouses(db: AsyncSession, tenant_id: str) -> int:
    """Active org nodes — the exact count check_plan_create_warehouse enforces
    against max_warehouses + 1 (one free root node)."""
    result = await db.execute(
        text(
            "SELECT COUNT(*) FROM organization_node "
            "WHERE tenant_id = :tid AND is_active = true"
        ),
        {"tid": str(tenant_id)},
    )
    return int(result.scalar() or 0)


async def get_plan_usage(db: AsyncSession, tenant_id: str) -> dict[str, Any]:
    """Return the tenant's plan tier plus used/limit for skus, users, warehouses.

    limit is the effective cap from get_tenant_entitlements() — None means
    unlimited. For warehouses, the displayed limit is max_warehouses as
    stored (the free root node is not added here; check_plan_create_warehouse
    adds +1 only for its own total_allowed comparison).

    sku_cap: get_tenant_entitlements()["sku_cap"] is read from the SAME
    tenants.sku_cap column product-service's create_product reads directly
    today — same value, not a separate source.
    """
    entitlements = await get_tenant_entitlements(db, tenant_id)
    if not entitlements:
        return {}

    skus_used, users_used, warehouses_used = (
        await count_active_skus(db, tenant_id),
        await count_billable_users(db, tenant_id),
        await count_active_warehouses(db, tenant_id),
    )

    return {
        "plan_tier": entitlements["plan_tier"],
        "skus": {"used": skus_used, "limit": entitlements["sku_cap"]},
        "users": {"used": users_used, "limit": entitlements["max_users"]},
        "warehouses": {"used": warehouses_used, "limit": entitlements["max_warehouses"]},
    }
