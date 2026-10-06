"""Unit tests for shared.billing.payments — invoice/renewal pricing,
mark_paid idempotency + contract extension, and cancel/fail state guards.

Mocked session throughout (no real DB connection): db.execute is an AsyncMock
whose side_effect is the ordered list of results the production code expects
for each await db.execute(...) call, in call order."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from shared.billing.payments import (
    cancel_invoice,
    create_invoice,
    mark_failed,
    mark_paid,
    next_invoice_period,
)

pytestmark = pytest.mark.asyncio


def _db(side_effect: list) -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=side_effect)
    return db


def _result(fetchone=None, scalar_one=None) -> MagicMock:
    result = MagicMock()
    result.fetchone = MagicMock(return_value=fetchone)
    if scalar_one is not None:
        result.scalar_one = MagicMock(return_value=scalar_one)
    return result


def _subscription(
    *,
    id="sub-1", tier="GROWTH", billing_period="MONTHLY", status="PENDING_PAYMENT",
    provider="MANUAL", price_id="price-1", amount=Decimal("200.00"), currency="ETB",
    current_period_start=date(2026, 10, 6), current_period_end=date(2026, 11, 6),
) -> MagicMock:
    row = MagicMock()
    row.id, row.tier, row.billing_period, row.status = id, tier, billing_period, status
    row.provider, row.price_id, row.amount, row.currency = provider, price_id, amount, currency
    row.current_period_start, row.current_period_end = current_period_start, current_period_end
    return row


def _price(*, id="price-1", tier="GROWTH", billing_period="MONTHLY", currency="ETB", amount=Decimal("200.00")) -> MagicMock:
    row = MagicMock()
    row.id, row.tier, row.billing_period, row.currency, row.amount = id, tier, billing_period, currency, amount
    return row


# ── next_invoice_period ──────────────────────────────────────────────────────

async def test_next_invoice_period_first_invoice_uses_snapshot_price() -> None:
    sub = _subscription(status="PENDING_PAYMENT", price_id="price-1", amount=Decimal("200.00"))
    snapshot_price = _price(id="price-1", amount=Decimal("200.00"))
    db = _db([
        _result(fetchone=None),            # no existing PAID payment -> first invoice
        _result(fetchone=snapshot_price),  # SELECT package_prices WHERE id = subscription.price_id
    ])

    start, end, price, is_renewal = await next_invoice_period(db, sub)

    assert is_renewal is False
    assert start == sub.current_period_start
    assert end == sub.current_period_end
    assert price.amount == Decimal("200.00")


async def test_next_invoice_period_renewal_uses_current_price_not_snapshot() -> None:
    """A renewal is priced at the CURRENT package price, which may differ
    from the subscription's own (older) snapshot amount."""
    sub = _subscription(status="ACTIVE", price_id="price-1", amount=Decimal("200.00"),
                         current_period_end=date(2026, 11, 6))
    current_price = _price(id="price-2", amount=Decimal("250.00"))
    db = _db([
        _result(fetchone=current_price),  # get_current_price()
    ])

    start, end, price, is_renewal = await next_invoice_period(db, sub)

    assert is_renewal is True
    assert start == date(2026, 11, 6)
    assert end == date(2026, 12, 6)
    assert price.amount == Decimal("250.00")  # NOT the subscription's 200.00 snapshot


async def test_next_invoice_period_pending_payment_with_existing_paid_is_a_renewal() -> None:
    """PENDING_PAYMENT but a PAID payment already exists for it (e.g. a past
    renewal moved it back to PENDING_PAYMENT) -> treated as a renewal, not
    the first invoice."""
    sub = _subscription(status="PENDING_PAYMENT")
    current_price = _price(amount=Decimal("300.00"))
    db = _db([
        _result(fetchone=MagicMock()),    # existing PAID payment found
        _result(fetchone=current_price),  # get_current_price()
    ])

    _, _, price, is_renewal = await next_invoice_period(db, sub)

    assert is_renewal is True
    assert price.amount == Decimal("300.00")


async def test_next_invoice_period_renewal_raises_when_no_price_available() -> None:
    sub = _subscription(status="ACTIVE")
    db = _db([_result(fetchone=None)])  # get_current_price() -> None

    with pytest.raises(ValueError, match="PRICE_NOT_AVAILABLE"):
        await next_invoice_period(db, sub)


# ── create_invoice ───────────────────────────────────────────────────────────

async def test_create_invoice_first_invoice_vat_on_200_is_30_and_230() -> None:
    sub = _subscription(status="PENDING_PAYMENT", price_id="price-1", amount=Decimal("200.00"))
    snapshot_price = _price(id="price-1", amount=Decimal("200.00"))
    tier_row = MagicMock(display_name="Growth")
    db = _db([
        _result(fetchone=sub),              # _get_live_subscription
        _result(fetchone=None),             # no existing PENDING payment
        _result(fetchone=None),             # no existing PAID payment (first invoice)
        _result(fetchone=snapshot_price),   # package_prices by id
        _result(scalar_one="payment-1"),    # INSERT payments RETURNING id
        _result(fetchone=tier_row),         # platform_tier_config.display_name
        _result(),                          # INSERT payment_line_items
    ])

    out = await create_invoice(db, "tenant-1", recorded_by="user-1")

    assert out["payment_id"] == "payment-1"
    assert out["is_renewal"] is False
    assert out["subtotal"] == Decimal("200.00")
    assert out["vat_amount"] == Decimal("30.00")
    assert out["total"] == Decimal("230.00")


async def test_create_invoice_no_live_subscription_raises() -> None:
    db = _db([_result(fetchone=None)])  # _get_live_subscription -> None

    with pytest.raises(ValueError, match="NO_LIVE_SUBSCRIPTION"):
        await create_invoice(db, "tenant-1")


async def test_create_invoice_already_pending_raises() -> None:
    sub = _subscription()
    db = _db([
        _result(fetchone=sub),           # _get_live_subscription
        _result(fetchone=MagicMock()),   # an existing PENDING payment
    ])

    with pytest.raises(ValueError, match="INVOICE_ALREADY_PENDING"):
        await create_invoice(db, "tenant-1")


# ── mark_paid ─────────────────────────────────────────────────────────────────

def _payment(*, id="payment-1", tenant_id="tenant-1", subscription_id="sub-1",
             status="PENDING", period_start=date(2026, 10, 6), period_end=date(2026, 11, 6)) -> MagicMock:
    row = MagicMock()
    row.id, row.tenant_id, row.subscription_id, row.status = id, tenant_id, subscription_id, status
    row.period_start, row.period_end = period_start, period_end
    return row


async def test_mark_paid_activates_subscription_and_extends_contract() -> None:
    payment = _payment(status="PENDING")
    line_item = MagicMock(price_id="price-1", amount=Decimal("200.00"))
    subscription = MagicMock(id="sub-1", price_id="price-1")

    db = _db([
        _result(fetchone=payment),       # SELECT payments FOR UPDATE
        _result(),                       # UPDATE payments
        _result(fetchone=line_item),     # SELECT payment_line_items
        _result(fetchone=subscription),  # SELECT subscriptions FOR UPDATE
        _result(),                       # UPDATE subscriptions (same price branch)
        _result(),                       # UPDATE tenants contract dates
    ])

    out = await mark_paid(db, "payment-1", provider="MANUAL", provider_reference="RCPT-1", recorded_by="sa-1")

    assert out == {"payment_id": "payment-1", "status": "PAID", "already_paid": False}


async def test_mark_paid_twice_second_call_is_idempotent_and_does_not_re_extend() -> None:
    """Second call sees status already PAID and returns immediately —
    contract_end is only ever touched by the FIRST call's UPDATE tenants."""
    already_paid_payment = _payment(status="PAID")
    db = _db([_result(fetchone=already_paid_payment)])  # SELECT payments FOR UPDATE only

    out = await mark_paid(db, "payment-1", provider="MANUAL")

    assert out == {"payment_id": "payment-1", "status": "PAID", "already_paid": True}
    assert db.execute.call_count == 1  # no UPDATE of any kind ran


async def test_mark_paid_invalid_state_for_failed_payment_raises() -> None:
    failed_payment = _payment(status="FAILED")
    db = _db([_result(fetchone=failed_payment)])

    with pytest.raises(ValueError, match="INVALID_PAYMENT_STATE"):
        await mark_paid(db, "payment-1", provider="MANUAL")


async def test_mark_paid_renewal_at_new_price_updates_subscription_price() -> None:
    """The payment's line item price differs from the subscription's current
    price_id -> the subscription moves onto the new price at renewal."""
    payment = _payment(status="PENDING")
    line_item = MagicMock(price_id="price-2", amount=Decimal("250.00"))
    subscription = MagicMock(id="sub-1", price_id="price-1")  # old price

    db = _db([
        _result(fetchone=payment),
        _result(),
        _result(fetchone=line_item),
        _result(fetchone=subscription),
        _result(),  # UPDATE subscriptions ... price_id = 'price-2'
        _result(),  # UPDATE tenants
    ])

    out = await mark_paid(db, "payment-1", provider="MANUAL")
    assert out["already_paid"] is False

    update_subscriptions_call = db.execute.call_args_list[4]
    sql_text = str(update_subscriptions_call.args[0])
    params = update_subscriptions_call.args[1]
    assert "price_id" in sql_text
    assert params["price_id"] == "price-2"
    assert params["amount"] == Decimal("250.00")


async def test_mark_paid_contract_end_never_moves_backwards() -> None:
    """GREATEST(COALESCE(contract_end, :end), :end) in the UPDATE tenants SQL
    is the mechanism — this test asserts the literal clause is present so a
    future edit can't silently drop it and start overwriting later dates."""
    payment = _payment(status="PENDING", period_end=date(2026, 11, 6))
    line_item = MagicMock(price_id="price-1", amount=Decimal("200.00"))
    subscription = MagicMock(id="sub-1", price_id="price-1")

    db = _db([
        _result(fetchone=payment),
        _result(),
        _result(fetchone=line_item),
        _result(fetchone=subscription),
        _result(),
        _result(),
    ])

    await mark_paid(db, "payment-1", provider="MANUAL")

    update_tenants_call = db.execute.call_args_list[5]
    sql_text = str(update_tenants_call.args[0])
    assert "GREATEST(COALESCE(contract_end" in sql_text


async def test_mark_paid_unknown_payment_raises_not_found() -> None:
    db = _db([_result(fetchone=None)])
    with pytest.raises(ValueError, match="PAYMENT_NOT_FOUND"):
        await mark_paid(db, "payment-x", provider="MANUAL")


# ── cancel_invoice / mark_failed ─────────────────────────────────────────────

async def test_cancel_invoice_from_pending_succeeds() -> None:
    db = _db([_result(fetchone=_payment(status="PENDING")), _result()])
    out = await cancel_invoice(db, "payment-1", recorded_by="sa-1", note="customer asked")
    assert out == {"payment_id": "payment-1", "status": "CANCELLED"}


async def test_cancel_invoice_from_paid_raises_invalid_state() -> None:
    db = _db([_result(fetchone=_payment(status="PAID"))])
    with pytest.raises(ValueError, match="INVALID_PAYMENT_STATE"):
        await cancel_invoice(db, "payment-1", recorded_by="sa-1", note="n/a")


async def test_mark_failed_from_pending_succeeds() -> None:
    db = _db([_result(fetchone=_payment(status="PENDING")), _result()])
    out = await mark_failed(db, "payment-1", provider_reference="FAIL-1")
    assert out == {"payment_id": "payment-1", "status": "FAILED"}


async def test_mark_failed_from_cancelled_raises_invalid_state() -> None:
    db = _db([_result(fetchone=_payment(status="CANCELLED"))])
    with pytest.raises(ValueError, match="INVALID_PAYMENT_STATE"):
        await mark_failed(db, "payment-1")
