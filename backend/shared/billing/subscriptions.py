"""Subscription and VAT helpers — the single writer of new subscriptions.

start_subscription() is the only place that INSERTs into subscriptions and
sets a tenant's contract_start/contract_end from a creation flow (SA create
or self sign-up). A plan change updating an existing LIVE subscription is a
separate concern (payment step, S5) — this module does not touch it.
"""
from __future__ import annotations

import calendar
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

VAT_RATE = Decimal("0.15")


def vat_breakdown(amount: Decimal) -> dict[str, Any]:
    """subtotal/vat_rate/vat_amount/total for a pre-VAT `amount`."""
    subtotal = Decimal(amount)
    vat_amount = (subtotal * VAT_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "subtotal": subtotal,
        "vat_rate": VAT_RATE,
        "vat_amount": vat_amount,
        "total": subtotal + vat_amount,
    }


async def get_current_price(db: AsyncSession, tier: str, billing_period: str) -> Optional[Any]:
    """The latest package_prices row for tier+billing_period with
    effective_from <= now(), or None if no price exists. Callers must never
    substitute a hardcoded amount when this returns None.

    Tie-break on created_at DESC: prices are append-only, so posting a correcting
    price with the SAME effective_from as a wrong one is the only way to fix it —
    the more-recently-created row must win."""
    return (await db.execute(
        text(
            "SELECT id, tier, billing_period, currency, amount, effective_from "
            "FROM package_prices "
            "WHERE tier = :tier AND billing_period = :period AND effective_from <= now() "
            "ORDER BY effective_from DESC, created_at DESC LIMIT 1"
        ),
        {"tier": tier, "period": billing_period},
    )).fetchone()


async def get_current_addon_price(db: AsyncSession, addon_code: str, billing_period: str) -> Optional[Any]:
    """The latest addon_prices row for addon_code+billing_period with
    effective_from <= now(), or None if no price exists (S10). Same
    append-only / tie-break semantics as get_current_price() above."""
    return (await db.execute(
        text(
            "SELECT id, addon_code, billing_period, currency, amount, effective_from "
            "FROM addon_prices "
            "WHERE addon_code = :code AND billing_period = :period AND effective_from <= now() "
            "ORDER BY effective_from DESC, created_at DESC LIMIT 1"
        ),
        {"code": addon_code, "period": billing_period},
    )).fetchone()


def period_end(start: date, billing_period: str) -> date:
    """MONTHLY: +1 calendar month, clamping the day (Jan 31 -> Feb 28/29).
    ANNUAL: +1 year, clamping Feb 29 -> Feb 28 on a non-leap target year."""
    if billing_period == "MONTHLY":
        year = start.year + (1 if start.month == 12 else 0)
        month = 1 if start.month == 12 else start.month + 1
    elif billing_period == "ANNUAL":
        year = start.year + 1
        month = start.month
    else:
        raise ValueError(f"Unknown billing_period: {billing_period}")

    last_day_of_month = calendar.monthrange(year, month)[1]
    return date(year, month, min(start.day, last_day_of_month))


async def start_subscription(
    db: AsyncSession,
    tenant_id: str,
    tier: str,
    billing_period: str,
    *,
    status: str,
    provider: str = "MANUAL",
    created_by: Optional[str] = None,
    start: Optional[date] = None,
) -> dict[str, Any]:
    """Create a subscriptions row from the current package price snapshot,
    and — only when the tenant has no contract dates yet — set
    tenants.contract_start/contract_end. Never overwrites dates an SA already
    set by hand.

    Raises ValueError("PRICE_NOT_AVAILABLE") if no current price exists for
    tier+billing_period; the caller maps this to HTTP 422.
    """
    start = start or date.today()
    end = period_end(start, billing_period)

    price = await get_current_price(db, tier, billing_period)
    if price is None:
        raise ValueError("PRICE_NOT_AVAILABLE")

    subscription_id = (await db.execute(
        text(
            "INSERT INTO subscriptions ("
            "  tenant_id, tier, billing_period, status, provider, price_id, amount, "
            "  currency, current_period_start, current_period_end, created_by"
            ") VALUES ("
            "  :tid, :tier, :period, :status, :provider, :price_id, :amount, "
            "  :currency, :start, :end, :created_by"
            ") RETURNING id"
        ),
        {
            "tid": str(tenant_id), "tier": tier, "period": billing_period,
            "status": status, "provider": provider, "price_id": str(price.id),
            "amount": price.amount, "currency": price.currency,
            "start": start, "end": end,
            "created_by": str(created_by) if created_by else None,
        },
    )).scalar_one()

    await db.execute(
        text(
            "UPDATE tenants SET contract_start = :start, contract_end = :end "
            "WHERE id = :tid AND contract_start IS NULL AND contract_end IS NULL"
        ),
        {"start": start, "end": end, "tid": str(tenant_id)},
    )

    return {
        "subscription_id": str(subscription_id),
        "status": status,
        "amount": price.amount,
        "currency": price.currency,
        "current_period_start": start,
        "current_period_end": end,
        **vat_breakdown(price.amount),
    }


async def update_live_subscription_tier(
    db: AsyncSession, tenant_id: str, new_tier: str
) -> Optional[dict[str, Any]]:
    """Plan change (SA PATCH /plan or TA profile plan change) updates the
    tenant's LIVE subscription tier and price snapshot immediately —
    entitlements change now, no proration. The new price is charged starting
    from the NEXT invoice; current_period_start/end and contract dates are
    untouched here.

    Returns {"old_tier", "new_tier", "old_amount", "new_amount"} for activity
    logging, or None if the tenant has no live subscription (caller logs a
    warning and does not create one here) or the tier is unchanged.

    Raises ValueError("PRICE_NOT_AVAILABLE") if no current price exists for
    new_tier at the subscription's billing_period.
    """
    sub = (await db.execute(
        text(
            "SELECT id, tier, billing_period, amount FROM subscriptions "
            "WHERE tenant_id = :tid AND status IN ('ACTIVE', 'PENDING_PAYMENT', 'PAST_DUE') "
            "LIMIT 1"
        ),
        {"tid": str(tenant_id)},
    )).fetchone()
    if sub is None or sub.tier == new_tier:
        return None

    price = await get_current_price(db, new_tier, sub.billing_period)
    if price is None:
        raise ValueError("PRICE_NOT_AVAILABLE")

    await db.execute(
        text(
            "UPDATE subscriptions SET tier = :tier, price_id = :price_id, "
            "       amount = :amount, updated_at = now() WHERE id = :sid"
        ),
        {"tier": new_tier, "price_id": str(price.id), "amount": price.amount, "sid": str(sub.id)},
    )
    return {
        "old_tier": sub.tier, "new_tier": new_tier,
        "old_amount": sub.amount, "new_amount": price.amount,
    }
