"""Mid-period proration for ANNUAL upgrades and PURCHASED add-ons (S11).

Replaces "plan change = no proration" (CLAUDE.md §15 S5) for this one case.
The business rule (agreed):

  Billing months, not calendar days. The current period is split into
  "billing months" of calendar length, each one a +1-month step from
  current_period_start. The partial billing month a change falls in is
  FREE; whole remaining billing months (from the next billing-month
  boundary STRICTLY AFTER today, up to current_period_end) are charged at
  the subscription's/add-on's ANNUAL rate:
    - upgrade:  (new_annual_price - old_annual_snapshot) * remaining_months / 12
    - add-on:   addon_annual_price * remaining_months / 12
  VAT on top. MONTHLY subscriptions always have remaining_months = 0 (no
  proration invoice — today's behaviour, unchanged). A downgrade, an
  OVERRIDE add-on, or a subscription that has never been paid never raises
  one either.

A PRORATION invoice is a second `payments` row (invoice_kind='PRORATION'),
raised automatically in the SAME DB transaction as the plan change / add-on
grant. Paying it changes nothing on the subscription or contract (see
payments.mark_paid()'s invoice_kind branch); cancelling it leaves the
change in place. It never blocks anything; a PENDING PERIOD invoice DOES
block a new upgrade or PURCHASED add-on grant (rule 6,
check_not_blocked_by_pending_period_invoice()).
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.billing.addons import grant_addon
from shared.billing.subscriptions import get_current_addon_price, get_current_price, update_live_subscription_tier, vat_breakdown


@dataclass(frozen=True)
class ProrationLine:
    item_type: str                       # 'PACKAGE' | 'ADDON'
    item_key: str                        # tier code or addon_code
    description: str
    amount: Decimal                      # already-prorated amount for this line (pre-VAT)
    price_id: Optional[str] = None       # PACKAGE lines — package_prices id
    addon_price_id: Optional[str] = None  # ADDON lines — addon_prices id


# ── month-boundary arithmetic ────────────────────────────────────────────────

def _add_months(d: date, n: int) -> date:
    """`d` plus `n` calendar months, day-clamped the same way as
    subscriptions.period_end() (Jan 31 + 1 month -> Feb 28/29). ABSOLUTE
    from `d` every time — never cumulative from a previously-clamped
    boundary. Cumulative stepping would drift the clamped day downward
    every time it crosses a short month (a Jan-31 start would clamp to
    the 28th in February and then STAY at 28 for every month after,
    since min(28, x) = 28 for every month with >= 28 days) — so the 12th
    cumulative step would never land back on the subscription's real
    current_period_end for a day-29/30/31 start. Stepping absolutely from
    the original day each time reproduces exactly the arithmetic
    subscriptions.period_end() uses for a single +1 YEAR step, so
    _add_months(start, 12) always equals an ANNUAL period's
    current_period_end, and _add_months(start, 1) always equals a
    MONTHLY period's.
    """
    total = d.month - 1 + n
    year = d.year + total // 12
    month = total % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


def _billing_months_in_period(period_start: date, period_end: date) -> int:
    """Whole +1-month steps from period_start needed to reach period_end
    (1 for a MONTHLY period, 12 for ANNUAL, by construction above)."""
    n = 1
    while _add_months(period_start, n) < period_end and n <= 24:
        n += 1
    return n


def _last_boundary_index(period_start: date, total_months: int, today: date) -> int:
    """Index (0-based) of the last billing-month boundary <= today, among
    the `total_months` boundaries that each start a billing month
    (boundary[0] = period_start, boundary[total_months-1] = the start of
    the LAST billing month — period_end itself is not in this list).
    `today` exactly ON a boundary counts as having reached it: the free
    month is the one STARTING there, not the one ending there."""
    m = -1
    for n in range(total_months):
        if _add_months(period_start, n) <= today:
            m = n
        else:
            break
    return m if m != -1 else 0


def remaining_billing_months(period_start: date, period_end: date, today: date) -> int:
    """Whole billing months left to charge: the billing month `today` falls
    in is free; this counts the whole months strictly after it, up to
    period_end. 0 for a MONTHLY period always (there is only one billing
    month in it). 0..11 for an ANNUAL period. On the boundary day itself,
    the NEW month starting there is the free one (e.g. today exactly on a
    mid-period boundary with 6 whole months before period_end -> 6, not 7:
    the boundary day starts a fresh free month, it does not end the
    previous paid one)."""
    total_months = _billing_months_in_period(period_start, period_end)
    if total_months <= 0:
        return 0
    m = _last_boundary_index(period_start, total_months, today)
    return max(0, min((total_months - 1) - m, total_months - 1))


def _free_until(period_start: date, period_end: date, today: date) -> date:
    """The next billing-month boundary strictly after `today` — i.e. where
    the free partial billing month ends and chargeable months begin."""
    total_months = _billing_months_in_period(period_start, period_end)
    m = _last_boundary_index(period_start, total_months, today)
    return _add_months(period_start, m + 1)


def prorate(annual_amount: Decimal, months: int) -> Decimal:
    """`annual_amount` x `months` / 12, quantized 0.01 ROUND_HALF_UP."""
    return (Decimal(annual_amount) * Decimal(months) / Decimal(12)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


# ── subscription / invoice lookups ───────────────────────────────────────────

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


async def _has_paid_payment(db: AsyncSession, subscription_id: str) -> bool:
    row = (await db.execute(
        text("SELECT id FROM payments WHERE subscription_id = :sid AND status = 'PAID' LIMIT 1"),
        {"sid": str(subscription_id)},
    )).fetchone()
    return row is not None


async def _has_pending_period_invoice(db: AsyncSession, subscription_id: str) -> bool:
    row = (await db.execute(
        text(
            "SELECT id FROM payments WHERE subscription_id = :sid "
            "AND status = 'PENDING' AND invoice_kind = 'PERIOD' LIMIT 1"
        ),
        {"sid": str(subscription_id)},
    )).fetchone()
    return row is not None


async def _never_paid(db: AsyncSession, sub: Any) -> bool:
    return sub.status == "PENDING_PAYMENT" and not await _has_paid_payment(db, sub.id)


async def check_not_blocked_by_pending_period_invoice(db: AsyncSession, tenant_id: str) -> None:
    """Raises ValueError("INVOICE_PENDING_SETTLE_FIRST") if the tenant's live
    subscription has a PENDING invoice_kind='PERIOD' payment (rule 6) — SA
    must mark it paid or cancel it before an upgrade or a PURCHASED add-on
    grant proceeds. A PENDING PRORATION invoice never blocks anything. No
    live subscription -> nothing to block."""
    sub = await _get_live_subscription(db, tenant_id)
    if sub is None:
        return
    if await _has_pending_period_invoice(db, sub.id):
        raise ValueError("INVOICE_PENDING_SETTLE_FIRST")


# ── invoice creation (write) ─────────────────────────────────────────────────

async def create_proration_invoice(
    db: AsyncSession,
    tenant_id: str,
    subscription: Any,
    lines: list[ProrationLine],
    reason: str,
    recorded_by: Optional[str],
) -> Optional[dict[str, Any]]:
    """Raise a PENDING PRORATION invoice (payments.invoice_kind='PRORATION')
    for `lines`, period_start = the next billing-month boundary strictly
    after today, period_end = subscription.current_period_end. Returns None
    (no row written) if the combined line subtotal is <= 0. Caller is
    responsible for only invoking this when remaining_billing_months(...)
    > 0 (rule 5) and check_not_blocked_by_pending_period_invoice() has
    already passed (rule 6) — this function does not re-check either.
    `subscription` needs .id, .provider, .currency, .current_period_start,
    .current_period_end (the shape _get_live_subscription() returns).
    """
    subtotal = sum((Decimal(line.amount) for line in lines), Decimal("0"))
    if subtotal <= 0:
        return None

    today = date.today()
    free_until = _free_until(subscription.current_period_start, subscription.current_period_end, today)

    breakdown = vat_breakdown(subtotal)
    payment_id = (await db.execute(
        text(
            "INSERT INTO payments ("
            "  tenant_id, subscription_id, status, currency, subtotal, vat_rate, "
            "  vat_amount, total, period_start, period_end, provider, invoice_kind, "
            "  recorded_by, note"
            ") VALUES ("
            "  :tid, :sid, 'PENDING', :currency, :subtotal, :vat_rate, "
            "  :vat_amount, :total, :start, :end, :provider, 'PRORATION', "
            "  :recorded_by, :note"
            ") RETURNING id"
        ),
        {
            "tid": str(tenant_id), "sid": str(subscription.id),
            "currency": subscription.currency,
            "subtotal": breakdown["subtotal"], "vat_rate": breakdown["vat_rate"],
            "vat_amount": breakdown["vat_amount"], "total": breakdown["total"],
            "start": free_until, "end": subscription.current_period_end,
            "provider": subscription.provider,
            "recorded_by": str(recorded_by) if recorded_by else None,
            "note": reason,
        },
    )).scalar_one()

    for line in lines:
        await db.execute(
            text(
                "INSERT INTO payment_line_items ("
                "  tenant_id, payment_id, item_type, item_key, description, "
                "  price_id, addon_price_id, quantity, unit_amount, amount"
                ") VALUES ("
                "  :tid, :pid, :item_type, :item_key, :description, "
                "  :price_id, :addon_price_id, 1, :amount, :amount"
                ")"
            ),
            {
                "tid": str(tenant_id), "pid": str(payment_id),
                "item_type": line.item_type, "item_key": line.item_key,
                "description": line.description,
                "price_id": line.price_id, "addon_price_id": line.addon_price_id,
                "amount": line.amount,
            },
        )

    return {
        "payment_id": str(payment_id), "status": "PENDING", "invoice_kind": "PRORATION",
        "period_start": free_until, "period_end": subscription.current_period_end,
        **breakdown,
    }


# ── orchestration: wraps the existing write with the S11 rule ───────────────

async def apply_plan_change_with_proration(
    db: AsyncSession, tenant_id: str, new_tier: str, *, recorded_by: Optional[str],
) -> dict[str, Any]:
    """Wraps update_live_subscription_tier with the S11 proration rule.
    Entitlements (apply_package_to_tenant) are the caller's concern, as
    today — this only touches the subscription row + an optional proration
    invoice, both in the same transaction as the rest of the plan change.

    Returns {"subscription_change": dict|None, "proration_invoice": dict|None}.
    Raises ValueError("PRICE_NOT_AVAILABLE") (unchanged) or
    ValueError("INVOICE_PENDING_SETTLE_FIRST") (rule 6, upgrades only —
    never raised for a downgrade or same/lower price).
    """
    sub_before = await _get_live_subscription(db, tenant_id)
    if sub_before is not None and sub_before.tier != new_tier:
        new_price_check = await get_current_price(db, new_tier, sub_before.billing_period)
        if new_price_check is not None and Decimal(new_price_check.amount) > Decimal(sub_before.amount):
            # Inlined rather than check_not_blocked_by_pending_period_invoice(db, tenant_id) —
            # sub_before is already loaded, no need to fetch it a second time.
            if await _has_pending_period_invoice(db, sub_before.id):
                raise ValueError("INVOICE_PENDING_SETTLE_FIRST")

    subscription_change = await update_live_subscription_tier(db, tenant_id, new_tier)

    proration_invoice = None
    if subscription_change is not None and sub_before is not None:
        old_amount = Decimal(subscription_change["old_amount"])
        new_amount = Decimal(subscription_change["new_amount"])
        if sub_before.billing_period == "ANNUAL" and new_amount > old_amount and not await _never_paid(db, sub_before):
            months = remaining_billing_months(sub_before.current_period_start, sub_before.current_period_end, date.today())
            if months > 0:
                new_price_row = await get_current_price(db, new_tier, sub_before.billing_period)
                line = ProrationLine(
                    item_type="PACKAGE", item_key=new_tier,
                    description=f"Upgrade {subscription_change['old_tier']} -> {new_tier} "
                                f"— {months}/12 of annual difference",
                    amount=prorate(new_amount - old_amount, months),
                    price_id=str(new_price_row.id) if new_price_row is not None else None,
                )
                proration_invoice = await create_proration_invoice(
                    db, tenant_id, sub_before, [line],
                    reason=f"Upgrade {subscription_change['old_tier']} -> {new_tier}",
                    recorded_by=recorded_by,
                )

    return {"subscription_change": subscription_change, "proration_invoice": proration_invoice}


async def apply_addon_grant_with_proration(
    db: AsyncSession,
    tenant_id: str,
    addon_code: str,
    source: str,
    *,
    note: Optional[str] = None,
    starts_on=None,
    ends_on=None,
    created_by: Optional[str] = None,
) -> dict[str, Any]:
    """Wraps grant_addon with the S11 proration rule for PURCHASED grants.
    OVERRIDE grants are free and untouched by this — same ValueError codes
    as grant_addon(), plus ValueError("INVOICE_PENDING_SETTLE_FIRST")
    (rule 6, PURCHASED only, raised before grant_addon runs).

    Returns {"grant": dict, "proration_invoice": dict|None}.
    """
    if source == "PURCHASED":
        await check_not_blocked_by_pending_period_invoice(db, tenant_id)

    result = await grant_addon(
        db, tenant_id, addon_code, source,
        note=note, starts_on=starts_on, ends_on=ends_on, created_by=created_by,
    )

    proration_invoice = None
    if source == "PURCHASED":
        sub = await _get_live_subscription(db, tenant_id)
        if sub is not None and sub.billing_period == "ANNUAL" and not await _never_paid(db, sub):
            months = remaining_billing_months(sub.current_period_start, sub.current_period_end, date.today())
            if months > 0:
                line = ProrationLine(
                    item_type="ADDON", item_key=addon_code,
                    description=f"{addon_code} add-on — {months}/12 of annual price",
                    amount=prorate(Decimal(result["amount"]), months),
                    addon_price_id=result["price_id"],
                )
                proration_invoice = await create_proration_invoice(
                    db, tenant_id, sub, [line],
                    reason=f"Purchased add-on {addon_code}",
                    recorded_by=created_by,
                )

    return {"grant": result, "proration_invoice": proration_invoice}


# ── read-only previews (no writes) ───────────────────────────────────────────

def _empty_preview() -> dict[str, Any]:
    zero = vat_breakdown(Decimal("0"))
    return {
        "remaining_months": 0, "free_until": None, "period_end": None,
        "old_amount": None, "new_amount": None,
        "subtotal": zero["subtotal"], "vat": zero["vat_amount"], "total": zero["total"],
        "currency": None, "will_invoice": False, "blocked_code": None,
    }


async def preview_upgrade(db: AsyncSession, tenant_id: str, new_tier: str) -> dict[str, Any]:
    """Read-only — no writes. Same decision logic as
    apply_plan_change_with_proration(), without applying anything."""
    sub = await _get_live_subscription(db, tenant_id)
    if sub is None:
        return _empty_preview()

    new_price = await get_current_price(db, new_tier, sub.billing_period)
    old_amount = Decimal(sub.amount)
    new_amount = Decimal(new_price.amount) if new_price is not None else None
    is_upgrade = new_amount is not None and new_amount > old_amount

    blocked_code = None
    if is_upgrade and await _has_pending_period_invoice(db, sub.id):
        blocked_code = "INVOICE_PENDING_SETTLE_FIRST"

    months, subtotal, free_until = 0, Decimal("0"), None
    will_invoice = False
    if blocked_code is None and is_upgrade and sub.billing_period == "ANNUAL" and not await _never_paid(db, sub):
        months = remaining_billing_months(sub.current_period_start, sub.current_period_end, date.today())
        if months > 0:
            subtotal = prorate(new_amount - old_amount, months)
            if subtotal > 0:
                will_invoice = True
                free_until = _free_until(sub.current_period_start, sub.current_period_end, date.today())

    breakdown = vat_breakdown(subtotal)
    return {
        "remaining_months": months, "free_until": free_until, "period_end": sub.current_period_end,
        "old_amount": old_amount, "new_amount": new_amount,
        "subtotal": breakdown["subtotal"], "vat": breakdown["vat_amount"], "total": breakdown["total"],
        "currency": sub.currency, "will_invoice": will_invoice, "blocked_code": blocked_code,
    }


async def preview_addon(db: AsyncSession, tenant_id: str, addon_code: str) -> dict[str, Any]:
    """Read-only — no writes. Mirrors apply_addon_grant_with_proration()'s
    PURCHASED branch."""
    sub = await _get_live_subscription(db, tenant_id)
    if sub is None:
        return _empty_preview()

    price = await get_current_addon_price(db, addon_code, sub.billing_period)
    new_amount = Decimal(price.amount) if price is not None else None

    blocked_code = None
    if new_amount is not None and await _has_pending_period_invoice(db, sub.id):
        blocked_code = "INVOICE_PENDING_SETTLE_FIRST"

    months, subtotal, free_until = 0, Decimal("0"), None
    will_invoice = False
    if blocked_code is None and new_amount is not None and sub.billing_period == "ANNUAL" and not await _never_paid(db, sub):
        months = remaining_billing_months(sub.current_period_start, sub.current_period_end, date.today())
        if months > 0:
            subtotal = prorate(new_amount, months)
            if subtotal > 0:
                will_invoice = True
                free_until = _free_until(sub.current_period_start, sub.current_period_end, date.today())

    breakdown = vat_breakdown(subtotal)
    return {
        "remaining_months": months, "free_until": free_until, "period_end": sub.current_period_end,
        "old_amount": None, "new_amount": new_amount,
        "subtotal": breakdown["subtotal"], "vat": breakdown["vat_amount"], "total": breakdown["total"],
        "currency": sub.currency, "will_invoice": will_invoice, "blocked_code": blocked_code,
    }
