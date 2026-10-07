"""Tenant add-on lifecycle — the single writer of new `tenant_addons` rows
and the only place one moves to CANCELLED (S10, migration 072).

OVERRIDE: free, SA-granted, amount=0, note required. PURCHASED: priced from
the tenant's live subscription's billing_period, snapshotting price_id and
amount at grant time — same price-snapshot pattern as subscriptions/payments
(backend/shared/billing/subscriptions.py, payments.py): a later price change
never retroactively changes what was already granted.

get_tenant_entitlements() (backend/shared/plans/catalog.py) is what makes a
grant here actually take effect — it OR's package feature_flags with every
currently-ACTIVE, in-window tenant_addons row. apply_package_to_tenant()
never touches this table, so a granted add-on survives a plan change.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.billing.subscriptions import get_current_addon_price


async def _get_addon(db: AsyncSession, addon_code: str) -> Any:
    return (await db.execute(
        text("SELECT code, display_name, is_active FROM platform_addons WHERE code = :code"),
        {"code": addon_code},
    )).fetchone()


async def _get_live_subscription(db: AsyncSession, tenant_id: str) -> Any:
    return (await db.execute(
        text(
            "SELECT id, billing_period FROM subscriptions "
            "WHERE tenant_id = :tid AND status IN ('ACTIVE', 'PENDING_PAYMENT', 'PAST_DUE') "
            "LIMIT 1"
        ),
        {"tid": str(tenant_id)},
    )).fetchone()


async def grant_addon(
    db: AsyncSession,
    tenant_id: str,
    addon_code: str,
    source: str,
    *,
    note: Optional[str] = None,
    starts_on: Optional[date] = None,
    ends_on: Optional[date] = None,
    created_by: Optional[str] = None,
) -> dict[str, Any]:
    """Grant a free OVERRIDE or priced PURCHASED add-on to a tenant.

    Raises ValueError with one of: INVALID_SOURCE, ADDON_NOT_FOUND,
    ADDON_INACTIVE, FEATURE_ALREADY_IN_PACKAGE, ADDON_ALREADY_ACTIVE,
    NOTE_REQUIRED (OVERRIDE), NO_LIVE_SUBSCRIPTION / ADDON_PRICE_NOT_AVAILABLE
    (PURCHASED).
    """
    if source not in ("OVERRIDE", "PURCHASED"):
        raise ValueError("INVALID_SOURCE")

    addon = await _get_addon(db, addon_code)
    if addon is None:
        raise ValueError("ADDON_NOT_FOUND")
    if not addon.is_active:
        raise ValueError("ADDON_INACTIVE")

    tenant_row = (await db.execute(
        text("SELECT plan_tier FROM tenants WHERE id = :tid"), {"tid": str(tenant_id)},
    )).fetchone()
    if tenant_row and tenant_row.plan_tier:
        package = (await db.execute(
            text("SELECT feature_flags FROM platform_tier_config WHERE tier = :tier"),
            {"tier": str(tenant_row.plan_tier)},
        )).fetchone()
        if package and bool((package.feature_flags or {}).get(addon_code)):
            raise ValueError("FEATURE_ALREADY_IN_PACKAGE")

    existing = (await db.execute(
        text(
            "SELECT id FROM tenant_addons "
            "WHERE tenant_id = :tid AND addon_code = :code AND status = 'ACTIVE'"
        ),
        {"tid": str(tenant_id), "code": addon_code},
    )).fetchone()
    if existing is not None:
        raise ValueError("ADDON_ALREADY_ACTIVE")

    price_id: Optional[str] = None
    amount = Decimal("0")

    if source == "OVERRIDE":
        if not note or not note.strip():
            raise ValueError("NOTE_REQUIRED")
    else:  # PURCHASED
        subscription = await _get_live_subscription(db, tenant_id)
        if subscription is None:
            raise ValueError("NO_LIVE_SUBSCRIPTION")
        price = await get_current_addon_price(db, addon_code, subscription.billing_period)
        if price is None:
            raise ValueError("ADDON_PRICE_NOT_AVAILABLE")
        price_id = str(price.id)
        amount = Decimal(price.amount)

    new_id = (await db.execute(
        text(
            "INSERT INTO tenant_addons "
            "  (tenant_id, addon_code, source, status, price_id, amount, "
            "   starts_on, ends_on, note, created_by) "
            "VALUES (:tid, :code, :source, 'ACTIVE', :price_id, :amount, "
            "        COALESCE(:starts_on, CURRENT_DATE), :ends_on, :note, :created_by) "
            "RETURNING id"
        ),
        {
            "tid": str(tenant_id), "code": addon_code, "source": source,
            "price_id": price_id, "amount": amount,
            "starts_on": starts_on, "ends_on": ends_on,
            "note": note, "created_by": str(created_by) if created_by else None,
        },
    )).scalar_one()

    return {
        "id": str(new_id), "tenant_id": str(tenant_id), "addon_code": addon_code,
        "source": source, "status": "ACTIVE", "amount": amount, "price_id": price_id,
    }


async def cancel_addon(
    db: AsyncSession,
    tenant_id: str,
    tenant_addon_id: str,
    *,
    cancelled_by: Optional[str] = None,
) -> dict[str, Any]:
    """Raises ValueError ADDON_GRANT_NOT_FOUND or ADDON_NOT_ACTIVE."""
    row = (await db.execute(
        text("SELECT id, tenant_id, status, addon_code FROM tenant_addons WHERE id = :id"),
        {"id": str(tenant_addon_id)},
    )).fetchone()
    if row is None or str(row.tenant_id) != str(tenant_id):
        raise ValueError("ADDON_GRANT_NOT_FOUND")
    if row.status != "ACTIVE":
        raise ValueError("ADDON_NOT_ACTIVE")

    await db.execute(
        text(
            "UPDATE tenant_addons SET status = 'CANCELLED', cancelled_at = now(), "
            "cancelled_by = :cb WHERE id = :id"
        ),
        {"cb": str(cancelled_by) if cancelled_by else None, "id": str(tenant_addon_id)},
    )
    return {"id": str(tenant_addon_id), "addon_code": row.addon_code, "status": "CANCELLED"}
