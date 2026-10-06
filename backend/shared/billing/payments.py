"""Invoice and payment lifecycle — the single writer of new `payments` and
`payment_line_items` rows, and the only place a payment moves to PAID
(extending the tenant's contract) or FAILED/CANCELLED.

Design (agreed, S5):
  - A subscription row holds the price snapshot. A price change applies at
    the NEXT renewal only — never to the currently-invoiced period.
  - VAT 15% via subscriptions.vat_breakdown(). Amounts are Decimal end to
    end; never float.
  - Paying extends the contract; nothing is enforced on non-payment yet.
  - Payments are never deleted; payment_line_items is append-only (DB rule).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.billing.subscriptions import get_current_price, period_end, vat_breakdown

_LIVE_SUBSCRIPTION_STATUSES = ("ACTIVE", "PENDING_PAYMENT", "PAST_DUE")


async def _get_live_subscription(db: AsyncSession, tenant_id: str) -> Any:
    return (await db.execute(
        text(
            "SELECT id, tenant_id, tier, billing_period, status, provider, price_id, "
            "       amount, currency, current_period_start, current_period_end "
            "FROM subscriptions "
            "WHERE tenant_id = :tid AND status IN ('ACTIVE', 'PENDING_PAYMENT', 'PAST_DUE') "
            "LIMIT 1"
        ),
        {"tid": str(tenant_id)},
    )).fetchone()


async def next_invoice_period(
    db: AsyncSession, subscription: Any
) -> tuple[date, date, Any, bool]:
    """The period + price the next invoice for `subscription` should bill.

    - PENDING_PAYMENT with no PAID payment yet for this subscription: the
      CURRENT period (current_period_start -> current_period_end) at the
      subscription's own price snapshot (is_renewal=False) — the first bill.
    - Otherwise: a renewal. start = current_period_end, end computed from
      billing_period, priced at the CURRENT package price at invoice time
      (is_renewal=True) — a price change applies here, not retroactively.

    Returns (start, end, price_row, is_renewal). Raises ValueError
    ("PRICE_NOT_AVAILABLE") if no current price exists for a renewal.
    """
    is_first_invoice = False
    if subscription.status == "PENDING_PAYMENT":
        existing_paid = (await db.execute(
            text("SELECT id FROM payments WHERE subscription_id = :sid AND status = 'PAID' LIMIT 1"),
            {"sid": str(subscription.id)},
        )).fetchone()
        is_first_invoice = existing_paid is None

    if is_first_invoice:
        price = (await db.execute(
            text("SELECT id, tier, billing_period, currency, amount FROM package_prices WHERE id = :pid"),
            {"pid": str(subscription.price_id)},
        )).fetchone()
        return subscription.current_period_start, subscription.current_period_end, price, False

    start = subscription.current_period_end
    end = period_end(start, subscription.billing_period)
    price = await get_current_price(db, subscription.tier, subscription.billing_period)
    if price is None:
        raise ValueError("PRICE_NOT_AVAILABLE")
    return start, end, price, True


async def create_invoice(
    db: AsyncSession,
    tenant_id: str,
    *,
    recorded_by: Optional[str] = None,
    note: Optional[str] = None,
) -> dict[str, Any]:
    """Raise a new PENDING invoice (payment + one PACKAGE line item) for the
    tenant's live subscription.

    Raises ValueError("NO_LIVE_SUBSCRIPTION") if the tenant has no live
    subscription, or ValueError("INVOICE_ALREADY_PENDING") if one PENDING
    payment already exists for it.
    """
    subscription = await _get_live_subscription(db, tenant_id)
    if subscription is None:
        raise ValueError("NO_LIVE_SUBSCRIPTION")

    existing_pending = (await db.execute(
        text("SELECT id FROM payments WHERE subscription_id = :sid AND status = 'PENDING' LIMIT 1"),
        {"sid": str(subscription.id)},
    )).fetchone()
    if existing_pending is not None:
        raise ValueError("INVOICE_ALREADY_PENDING")

    start, end, price, is_renewal = await next_invoice_period(db, subscription)
    breakdown = vat_breakdown(Decimal(price.amount))

    payment_id = (await db.execute(
        text(
            "INSERT INTO payments ("
            "  tenant_id, subscription_id, status, currency, subtotal, vat_rate, "
            "  vat_amount, total, period_start, period_end, provider, recorded_by, note"
            ") VALUES ("
            "  :tid, :sid, 'PENDING', :currency, :subtotal, :vat_rate, "
            "  :vat_amount, :total, :start, :end, :provider, :recorded_by, :note"
            ") RETURNING id"
        ),
        {
            "tid": str(tenant_id), "sid": str(subscription.id),
            "currency": price.currency,
            "subtotal": breakdown["subtotal"], "vat_rate": breakdown["vat_rate"],
            "vat_amount": breakdown["vat_amount"], "total": breakdown["total"],
            "start": start, "end": end,
            "provider": subscription.provider,
            "recorded_by": str(recorded_by) if recorded_by else None,
            "note": note,
        },
    )).scalar_one()

    package = (await db.execute(
        text("SELECT display_name FROM platform_tier_config WHERE tier = :tier"),
        {"tier": subscription.tier},
    )).fetchone()
    display_name = package.display_name if package and package.display_name else subscription.tier

    await db.execute(
        text(
            "INSERT INTO payment_line_items ("
            "  tenant_id, payment_id, item_type, item_key, description, "
            "  price_id, quantity, unit_amount, amount"
            ") VALUES ("
            "  :tid, :pid, 'PACKAGE', :item_key, :description, "
            "  :price_id, 1, :amount, :amount"
            ")"
        ),
        {
            "tid": str(tenant_id), "pid": str(payment_id),
            "item_key": subscription.tier,
            "description": f"{display_name} — {subscription.billing_period}",
            "price_id": str(price.id),
            "amount": breakdown["subtotal"],
        },
    )

    return {
        "payment_id": str(payment_id),
        "status": "PENDING",
        "subscription_id": str(subscription.id),
        "is_renewal": is_renewal,
        "period_start": start,
        "period_end": end,
        "provider": subscription.provider,
        **breakdown,
    }


async def mark_paid(
    db: AsyncSession,
    payment_id: str,
    *,
    provider: str,
    provider_reference: Optional[str] = None,
    paid_at: Optional[datetime] = None,
    recorded_by: Optional[str] = None,
    note: Optional[str] = None,
) -> dict[str, Any]:
    """Mark a payment PAID: idempotent (a second call returns the already-paid
    row unchanged, with already_paid=True), activates the subscription, moves
    it to the paid period/price, and extends tenants.contract_end (never
    backwards; contract_start is set only if still unset).

    Raises ValueError("PAYMENT_NOT_FOUND") if no such payment, or
    ValueError("INVALID_PAYMENT_STATE") if it is not PENDING or already PAID
    (i.e. FAILED/CANCELLED/REFUNDED).
    """
    payment = (await db.execute(
        text(
            "SELECT id, tenant_id, subscription_id, status, period_start, period_end "
            "FROM payments WHERE id = :pid FOR UPDATE"
        ),
        {"pid": str(payment_id)},
    )).fetchone()
    if payment is None:
        raise ValueError("PAYMENT_NOT_FOUND")

    if payment.status == "PAID":
        return {"payment_id": str(payment.id), "status": "PAID", "already_paid": True}
    if payment.status != "PENDING":
        raise ValueError("INVALID_PAYMENT_STATE")

    paid_at = paid_at or datetime.now(timezone.utc)

    await db.execute(
        text(
            "UPDATE payments SET status = 'PAID', paid_at = :paid_at, "
            "       provider = :provider, provider_reference = :pref, "
            "       recorded_by = COALESCE(:recorded_by, recorded_by), "
            "       note = COALESCE(:note, note), updated_at = now() "
            "WHERE id = :pid"
        ),
        {
            "paid_at": paid_at, "provider": provider, "pref": provider_reference,
            "recorded_by": str(recorded_by) if recorded_by else None,
            "note": note, "pid": str(payment.id),
        },
    )

    line_item = (await db.execute(
        text(
            "SELECT pli.price_id, pli.amount, pp.tier AS price_tier "
            "FROM payment_line_items pli "
            "JOIN package_prices pp ON pp.id = pli.price_id "
            "WHERE pli.payment_id = :pid LIMIT 1"
        ),
        {"pid": str(payment.id)},
    )).fetchone()

    subscription = (await db.execute(
        text("SELECT id, tier, price_id FROM subscriptions WHERE id = :sid FOR UPDATE"),
        {"sid": str(payment.subscription_id)},
    )).fetchone()

    # Adopt the invoice's line-item price onto the subscription ONLY when that price
    # row's tier still matches the subscription's CURRENT tier. If the plan was changed
    # between invoicing and payment, the line item belongs to a tier the subscription has
    # since moved away from — adopting it would silently overwrite the new tier's price
    # with the old tier's. In that case we keep the subscription's current price and only
    # move the period + status (the else branch below).
    if (
        line_item is not None
        and str(line_item.price_id) != str(subscription.price_id)
        and line_item.price_tier == subscription.tier
    ):
        # Renewal at a new price within the same tier — the subscription moves onto the new snapshot.
        await db.execute(
            text(
                "UPDATE subscriptions SET status = 'ACTIVE', "
                "       current_period_start = :start, current_period_end = :end, "
                "       price_id = :price_id, amount = :amount, updated_at = now() "
                "WHERE id = :sid"
            ),
            {
                "start": payment.period_start, "end": payment.period_end,
                "price_id": str(line_item.price_id), "amount": line_item.amount,
                "sid": str(subscription.id),
            },
        )
    else:
        await db.execute(
            text(
                "UPDATE subscriptions SET status = 'ACTIVE', "
                "       current_period_start = :start, current_period_end = :end, "
                "       updated_at = now() "
                "WHERE id = :sid"
            ),
            {"start": payment.period_start, "end": payment.period_end, "sid": str(subscription.id)},
        )

    await db.execute(
        text(
            "UPDATE tenants SET "
            "  contract_start = COALESCE(contract_start, :start), "
            "  contract_end   = GREATEST(COALESCE(contract_end, :end), :end), "
            "  updated_at = now() "
            "WHERE id = :tid"
        ),
        {"start": payment.period_start, "end": payment.period_end, "tid": str(payment.tenant_id)},
    )

    return {"payment_id": str(payment.id), "status": "PAID", "already_paid": False}


async def mark_failed(
    db: AsyncSession,
    payment_id: str,
    *,
    provider_reference: Optional[str] = None,
    note: Optional[str] = None,
) -> dict[str, Any]:
    """PENDING -> FAILED only. Raises ValueError("INVALID_PAYMENT_STATE") otherwise."""
    payment = (await db.execute(
        text("SELECT id, status FROM payments WHERE id = :pid FOR UPDATE"),
        {"pid": str(payment_id)},
    )).fetchone()
    if payment is None:
        raise ValueError("PAYMENT_NOT_FOUND")
    if payment.status != "PENDING":
        raise ValueError("INVALID_PAYMENT_STATE")

    await db.execute(
        text(
            "UPDATE payments SET status = 'FAILED', provider_reference = :pref, "
            "       note = COALESCE(:note, note), updated_at = now() WHERE id = :pid"
        ),
        {"pref": provider_reference, "note": note, "pid": str(payment.id)},
    )
    return {"payment_id": str(payment.id), "status": "FAILED"}


async def cancel_invoice(
    db: AsyncSession,
    payment_id: str,
    *,
    recorded_by: str,
    note: str,
) -> dict[str, Any]:
    """PENDING -> CANCELLED only. Raises ValueError("INVALID_PAYMENT_STATE") otherwise."""
    payment = (await db.execute(
        text("SELECT id, status FROM payments WHERE id = :pid FOR UPDATE"),
        {"pid": str(payment_id)},
    )).fetchone()
    if payment is None:
        raise ValueError("PAYMENT_NOT_FOUND")
    if payment.status != "PENDING":
        raise ValueError("INVALID_PAYMENT_STATE")

    await db.execute(
        text(
            "UPDATE payments SET status = 'CANCELLED', recorded_by = :recorded_by, "
            "       note = :note, updated_at = now() WHERE id = :pid"
        ),
        {"recorded_by": str(recorded_by), "note": note, "pid": str(payment.id)},
    )
    return {"payment_id": str(payment.id), "status": "CANCELLED"}
