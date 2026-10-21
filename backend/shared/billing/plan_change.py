"""Plan changes — SCHEDULE a paid downgrade for the next renewal, or apply
any other plan change immediately (S13, Alex's decisions 2026-10-07).

  - A downgrade is: the new tier's CURRENT price (same billing_period) is
    less than the live subscription's current amount.
  - A paid-at-least-once subscription + downgrade + effective="RENEWAL"
    (the default) -> SCHEDULE only: nothing else changes now. The switch
    happens when the renewal PERIOD invoice priced at scheduled_tier is
    marked PAID (shared.billing.payments.mark_paid).
  - effective="IMMEDIATE" (SA override), a never-paid subscription, or any
    upgrade/same-tier-with-cap-override -> today's immediate behaviour
    (apply_package_to_tenant + apply_plan_change_with_proration). No
    refund, no credit either way.
  - Any immediate change clears a previously scheduled downgrade — a
    tenant never has both an immediate change AND a pending schedule.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import shared.billing.proration as proration
from shared.billing.proration import apply_plan_change_with_proration
from shared.billing.subscriptions import get_current_price
from shared.plans.catalog import UNSET, apply_package_to_tenant

_VALID_EFFECTIVE = ("RENEWAL", "IMMEDIATE")


async def _get_live_subscription_for_update(db: AsyncSession, tenant_id: str) -> Any:
    return (
        await db.execute(
            text(
                "SELECT id, tenant_id, tier, billing_period, status, provider, price_id, "
                "       amount, currency, current_period_start, current_period_end, scheduled_tier "
                "FROM subscriptions "
                "WHERE tenant_id = :tid AND status IN ('ACTIVE', 'PENDING_PAYMENT', 'PAST_DUE') "
                "LIMIT 1 FOR UPDATE"
            ),
            {"tid": str(tenant_id)},
        )
    ).fetchone()


async def _clear_schedule(db: AsyncSession, subscription_id: str) -> None:
    await db.execute(
        text(
            "UPDATE subscriptions SET scheduled_tier = NULL, scheduled_at = NULL, "
            "       scheduled_by = NULL, updated_at = now() "
            "WHERE id = :sid"
        ),
        {"sid": str(subscription_id)},
    )


async def _find_pending_old_tier_period_invoice(
    db: AsyncSession, subscription_id: str, old_tier: str
) -> Optional[str]:
    """A PENDING PERIOD invoice already raised for this subscription, priced
    at `old_tier` — i.e. the renewal invoice from BEFORE this downgrade was
    scheduled. Surfaced so the caller can flag it (it will need re-raising
    or cancelling at the scheduled_tier price once the renewal is due)."""
    row = (
        await db.execute(
            text(
                "SELECT pli.payment_id AS id FROM payment_line_items pli "
                "JOIN payments p ON p.id = pli.payment_id "
                "JOIN package_prices pp ON pp.id = pli.price_id "
                "WHERE p.subscription_id = :sid AND p.status = 'PENDING' AND p.invoice_kind = 'PERIOD' "
                "  AND pli.item_type = 'PACKAGE' AND pp.tier = :tier LIMIT 1"
            ),
            {"sid": str(subscription_id), "tier": old_tier},
        )
    ).fetchone()
    return str(row.id) if row is not None else None


async def change_plan(
    db: AsyncSession,
    tenant_id: str,
    new_tier: str,
    *,
    effective: str = "RENEWAL",
    recorded_by: Optional[str],
    max_warehouses: Any = UNSET,
    max_users: Any = UNSET,
    sku_cap: Any = UNSET,
) -> dict[str, Any]:
    """Raises ValueError("INVALID_EFFECTIVE"), ValueError("PRICE_NOT_AVAILABLE"),
    ValueError("CAP_OVERRIDE_NOT_ALLOWED_WHEN_SCHEDULING"), or whatever
    apply_plan_change_with_proration()/apply_package_to_tenant() raise on the
    IMMEDIATE path (PRICE_NOT_AVAILABLE, INVOICE_PENDING_SETTLE_FIRST, an
    unknown tier).

    Returns one of:
      {"mode": "UNCHANGED", "scheduled_cleared": bool}
      {"mode": "SCHEDULED", "plan_tier", "scheduled_tier", "effective_at",
       "pending_renewal_invoice_id"}
      {"mode": "IMMEDIATE", "effective", "subscription_change", "proration_invoice"}
    """
    if effective not in _VALID_EFFECTIVE:
        raise ValueError("INVALID_EFFECTIVE")

    has_overrides = max_warehouses is not UNSET or max_users is not UNSET or sku_cap is not UNSET

    sub = await _get_live_subscription_for_update(db, tenant_id)

    if sub is not None and new_tier == sub.tier and not has_overrides:
        scheduled_cleared = sub.scheduled_tier is not None
        if scheduled_cleared:
            await _clear_schedule(db, sub.id)
        return {"mode": "UNCHANGED", "scheduled_cleared": scheduled_cleared}

    if sub is not None and effective == "RENEWAL" and new_tier != sub.tier:
        new_price = await get_current_price(db, new_tier, sub.billing_period)
        if new_price is None:
            raise ValueError("PRICE_NOT_AVAILABLE")
        is_downgrade = Decimal(new_price.amount) < Decimal(sub.amount)
        if is_downgrade and not await proration._never_paid(db, sub):
            if has_overrides:
                raise ValueError("CAP_OVERRIDE_NOT_ALLOWED_WHEN_SCHEDULING")
            await db.execute(
                text(
                    "UPDATE subscriptions SET scheduled_tier = :tier, scheduled_at = now(), "
                    "       scheduled_by = :by, updated_at = now() "
                    "WHERE id = :sid"
                ),
                {
                    "tier": new_tier,
                    "by": str(recorded_by) if recorded_by else None,
                    "sid": str(sub.id),
                },
            )
            pending_renewal_invoice_id = await _find_pending_old_tier_period_invoice(
                db, sub.id, sub.tier
            )
            return {
                "mode": "SCHEDULED",
                "plan_tier": sub.tier,
                "scheduled_tier": new_tier,
                "effective_at": sub.current_period_end,
                "pending_renewal_invoice_id": pending_renewal_invoice_id,
            }

    # IMMEDIATE: upgrade, effective=IMMEDIATE override, never-paid downgrade,
    # same-tier-with-cap-override, or no live subscription at all.
    if sub is not None and sub.scheduled_tier is not None:
        await _clear_schedule(db, sub.id)

    effective_package = await apply_package_to_tenant(
        db,
        tenant_id,
        new_tier,
        max_warehouses=max_warehouses,
        max_users=max_users,
        sku_cap=sku_cap,
    )
    plan_change = await apply_plan_change_with_proration(
        db, tenant_id, new_tier, recorded_by=recorded_by
    )
    return {
        "mode": "IMMEDIATE",
        "effective": effective_package,
        "subscription_change": plan_change["subscription_change"],
        "proration_invoice": plan_change["proration_invoice"],
    }


async def cancel_scheduled_downgrade(db: AsyncSession, tenant_id: str) -> dict[str, Any]:
    """Raises ValueError("NO_SCHEDULED_CHANGE") if nothing is scheduled."""
    sub = await _get_live_subscription_for_update(db, tenant_id)
    if sub is None or sub.scheduled_tier is None:
        raise ValueError("NO_SCHEDULED_CHANGE")

    cancelled_tier = sub.scheduled_tier
    await _clear_schedule(db, sub.id)
    return {"cancelled_tier": cancelled_tier}
