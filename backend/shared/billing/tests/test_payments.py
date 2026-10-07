"""Unit tests for shared.billing.payments — invoice/renewal pricing,
mark_paid idempotency + contract extension, and cancel/fail state guards.

Mocked session throughout (no real DB connection): db.execute is an AsyncMock
whose side_effect is the ordered list of results the production code expects
for each await db.execute(...) call, in call order."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

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


def _result(fetchone=None, scalar_one=None, fetchall=None) -> MagicMock:
    result = MagicMock()
    result.fetchone = MagicMock(return_value=fetchone)
    if scalar_one is not None:
        result.scalar_one = MagicMock(return_value=scalar_one)
    result.fetchall = MagicMock(return_value=fetchall if fetchall is not None else [])
    return result


def _subscription(
    *,
    id="sub-1", tier="GROWTH", billing_period="MONTHLY", status="PENDING_PAYMENT",
    provider="MANUAL", price_id="price-1", amount=Decimal("200.00"), currency="ETB",
    current_period_start=date(2026, 10, 6), current_period_end=date(2026, 11, 6),
    scheduled_tier=None,
) -> MagicMock:
    row = MagicMock()
    row.id, row.tier, row.billing_period, row.status = id, tier, billing_period, status
    row.provider, row.price_id, row.amount, row.currency = provider, price_id, amount, currency
    row.current_period_start, row.current_period_end = current_period_start, current_period_end
    row.scheduled_tier = scheduled_tier
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


async def test_next_invoice_period_renewal_uses_scheduled_tier_price_when_set() -> None:
    """S13: a scheduled downgrade re-prices the renewal at scheduled_tier,
    not the subscription's current tier."""
    sub = _subscription(status="ACTIVE", tier="GROWTH", scheduled_tier="STARTER",
                         price_id="price-1", amount=Decimal("200.00"),
                         current_period_end=date(2026, 11, 6))
    starter_price = _price(id="price-starter", tier="STARTER", amount=Decimal("100.00"))
    db = _db([_result(fetchone=starter_price)])

    start, end, price, is_renewal = await next_invoice_period(db, sub)

    assert is_renewal is True
    assert price.amount == Decimal("100.00")
    get_price_call = db.execute.call_args_list[0]
    assert get_price_call.args[1]["tier"] == "STARTER"


async def test_next_invoice_period_first_invoice_ignores_scheduled_tier() -> None:
    """The subscription's FIRST invoice is always at its own snapshot price —
    scheduled_tier only ever affects a renewal."""
    sub = _subscription(status="PENDING_PAYMENT", scheduled_tier="STARTER",
                         price_id="price-1", amount=Decimal("200.00"))
    snapshot_price = _price(id="price-1", amount=Decimal("200.00"))
    db = _db([
        _result(fetchone=None),            # no existing PAID payment -> first invoice
        _result(fetchone=snapshot_price),  # SELECT package_prices WHERE id = subscription.price_id
    ])

    start, end, price, is_renewal = await next_invoice_period(db, sub)

    assert is_renewal is False
    assert price.amount == Decimal("200.00")


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
        _result(fetchall=[]),               # _active_purchased_addons -> none
        _result(scalar_one="payment-1"),    # INSERT payments RETURNING id
        _result(fetchone=tier_row),         # platform_tier_config.display_name
        _result(),                          # INSERT payment_line_items (PACKAGE)
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


async def test_create_invoice_pending_check_is_scoped_to_period_invoice_kind() -> None:
    """S11: a PENDING PRORATION invoice must never block a normal PERIOD
    invoice (rule 6 is one-directional) — the existing-pending query is
    scoped to invoice_kind = 'PERIOD'."""
    sub = _subscription(status="PENDING_PAYMENT", price_id="price-1", amount=Decimal("200.00"))
    snapshot_price = _price(id="price-1", amount=Decimal("200.00"))
    db = _db([
        _result(fetchone=sub),               # _get_live_subscription
        _result(fetchone=None),               # existing-pending lookup (mocked: none found)
        _result(fetchone=None),               # no existing PAID payment (first invoice)
        _result(fetchone=snapshot_price),     # package_prices by id
        _result(fetchall=[]),                 # _active_purchased_addons
        _result(scalar_one="payment-1"),      # INSERT payments
        _result(fetchone=MagicMock(display_name="Growth")),
        _result(),                            # INSERT payment_line_items
    ])

    await create_invoice(db, "tenant-1")

    pending_check_call = db.execute.call_args_list[1]
    assert "invoice_kind = 'PERIOD'" in str(pending_check_call.args[0])


# ── create_invoice + add-ons (S10) ──────────────────────────────────────────────

def _addon_row(*, addon_code="LOGISTICS", price_id="addon-price-1", amount=Decimal("50.00"),
                display_name="Logistics & Fleet Management") -> MagicMock:
    row = MagicMock()
    row.addon_code, row.price_id, row.amount, row.display_name = addon_code, price_id, amount, display_name
    return row


async def test_create_invoice_package_plus_two_addons_correct_subtotal_vat_total() -> None:
    """First invoice: package (200) + two PURCHASED add-ons (50 + 20) at their
    grant-time snapshot prices -> subtotal 270, VAT 15% = 40.50, total 310.50."""
    sub = _subscription(status="PENDING_PAYMENT", price_id="price-1", amount=Decimal("200.00"))
    snapshot_price = _price(id="price-1", amount=Decimal("200.00"))
    tier_row = MagicMock(display_name="Growth")
    addon1 = _addon_row(addon_code="LOGISTICS", price_id="addon-price-1", amount=Decimal("50.00"))
    addon2 = _addon_row(addon_code="AUDIT_EXPORT", price_id="addon-price-2", amount=Decimal("20.00"),
                         display_name="Audit Log Export")

    db = _db([
        _result(fetchone=sub),                       # _get_live_subscription
        _result(fetchone=None),                       # no existing PENDING payment
        _result(fetchone=None),                       # no existing PAID payment (first invoice)
        _result(fetchone=snapshot_price),              # package_prices by id
        _result(fetchall=[addon1, addon2]),            # _active_purchased_addons
        _result(scalar_one="payment-1"),               # INSERT payments RETURNING id
        _result(fetchone=tier_row),                    # platform_tier_config.display_name
        _result(),                                      # INSERT payment_line_items (PACKAGE)
        _result(),                                      # INSERT payment_line_items (ADDON LOGISTICS)
        _result(),                                      # INSERT payment_line_items (ADDON AUDIT_EXPORT)
    ])

    out = await create_invoice(db, "tenant-1", recorded_by="user-1")

    assert out["subtotal"] == Decimal("270.00")
    assert out["vat_amount"] == Decimal("40.50")
    assert out["total"] == Decimal("310.50")

    addon_line_calls = db.execute.call_args_list[8:10]
    item_keys = {c.args[1]["item_key"] for c in addon_line_calls}
    assert item_keys == {"LOGISTICS", "AUDIT_EXPORT"}


async def test_create_invoice_renewal_reprices_addon_at_current_price() -> None:
    """Renewal invoice: a PURCHASED add-on's stale grant-time snapshot (price
    addon-price-OLD, 40.00) is NOT used — the add-on's CURRENT price for the
    subscription's billing_period (addon-price-NEW, 60.00) is billed instead,
    same rule as the package itself."""
    sub = _subscription(status="ACTIVE", tier="GROWTH", billing_period="MONTHLY",
                         current_period_end=date(2026, 11, 6))
    current_package_price = _price(id="price-growth-nov", amount=Decimal("200.00"))
    current_addon_price = MagicMock(id="addon-price-NEW", amount=Decimal("60.00"))
    tier_row = MagicMock(display_name="Growth")
    stale_addon = _addon_row(addon_code="AI_ANALYTICS", price_id="addon-price-OLD", amount=Decimal("40.00"),
                              display_name="AI Forecasting & Analytics")

    db = _db([
        _result(fetchone=sub),                        # _get_live_subscription
        _result(fetchone=None),                        # no existing PENDING payment
        _result(fetchone=current_package_price),       # next_invoice_period renewal: get_current_price
        _result(fetchall=[stale_addon]),                # _active_purchased_addons
        _result(fetchone=current_addon_price),          # get_current_addon_price (renewal re-price)
        _result(scalar_one="payment-2"),                # INSERT payments RETURNING id
        _result(fetchone=tier_row),                     # platform_tier_config.display_name
        _result(),                                       # INSERT payment_line_items (PACKAGE)
        _result(),                                       # INSERT payment_line_items (ADDON)
    ])

    out = await create_invoice(db, "tenant-1")

    assert out["is_renewal"] is True
    assert out["subtotal"] == Decimal("260.00")  # 200 + 60 (NOT 200 + 40)

    addon_line_call = db.execute.call_args_list[8]
    assert addon_line_call.args[1]["addon_price_id"] == "addon-price-NEW"
    assert addon_line_call.args[1]["amount"] == Decimal("60.00")


# ── mark_paid ─────────────────────────────────────────────────────────────────

def _payment(*, id="payment-1", tenant_id="tenant-1", subscription_id="sub-1",
             status="PENDING", period_start=date(2026, 10, 6), period_end=date(2026, 11, 6)) -> MagicMock:
    row = MagicMock()
    row.id, row.tenant_id, row.subscription_id, row.status = id, tenant_id, subscription_id, status
    row.period_start, row.period_end = period_start, period_end
    return row


async def test_mark_paid_activates_subscription_and_extends_contract() -> None:
    payment = _payment(status="PENDING")
    line_item = MagicMock(price_id="price-1", amount=Decimal("200.00"), price_tier="GROWTH")
    subscription = MagicMock(id="sub-1", tier="GROWTH", price_id="price-1", scheduled_tier=None)

    db = _db([
        _result(fetchone=payment),       # SELECT payments FOR UPDATE
        _result(),                       # UPDATE payments
        _result(fetchone=line_item),     # SELECT payment_line_items (PACKAGE)
        _result(fetchone=subscription),  # SELECT subscriptions FOR UPDATE
        _result(),                       # UPDATE subscriptions (same price branch)
        _result(),                       # UPDATE tenants contract dates
        _result(fetchall=[]),            # SELECT payment_line_items (ADDON) -> none
    ])

    out = await mark_paid(db, "payment-1", provider="MANUAL", provider_reference="RCPT-1", recorded_by="sa-1")

    assert out == {"payment_id": "payment-1", "status": "PAID", "already_paid": False, "downgrade_applied": None}


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
    price_id, but both are the SAME tier (a price change, not a plan change)
    -> the subscription moves onto the new price at renewal."""
    payment = _payment(status="PENDING")
    line_item = MagicMock(price_id="price-2", amount=Decimal("250.00"), price_tier="GROWTH")
    subscription = MagicMock(id="sub-1", tier="GROWTH", price_id="price-1", scheduled_tier=None)  # old price, same tier

    db = _db([
        _result(fetchone=payment),
        _result(),
        _result(fetchone=line_item),
        _result(fetchone=subscription),
        _result(),  # UPDATE subscriptions ... price_id = 'price-2'
        _result(),  # UPDATE tenants
        _result(fetchall=[]),  # SELECT payment_line_items (ADDON) -> none
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
    line_item = MagicMock(price_id="price-1", amount=Decimal("200.00"), price_tier="GROWTH")
    subscription = MagicMock(id="sub-1", tier="GROWTH", price_id="price-1", scheduled_tier=None)

    db = _db([
        _result(fetchone=payment),
        _result(),
        _result(fetchone=line_item),
        _result(fetchone=subscription),
        _result(),
        _result(),
        _result(fetchall=[]),  # SELECT payment_line_items (ADDON) -> none
    ])

    await mark_paid(db, "payment-1", provider="MANUAL")

    update_tenants_call = db.execute.call_args_list[5]
    sql_text = str(update_tenants_call.args[0])
    assert "GREATEST(COALESCE(contract_end" in sql_text


async def test_mark_paid_tier_changed_after_invoice_keeps_current_tier_price() -> None:
    """Exact bug sequence: an invoice is raised at tier STARTER, the plan is then
    changed to GROWTH (update_live_subscription_tier already moved the subscription
    onto GROWTH's price_id), and only THEN is the invoice paid. The line item's price
    belongs to STARTER, a tier the subscription has since left — mark_paid must NOT
    adopt it. It keeps the subscription's current (GROWTH) price and amount, moving
    only the period + status."""
    payment = _payment(status="PENDING")
    line_item = MagicMock(price_id="price-starter", amount=Decimal("100.00"), price_tier="STARTER")
    subscription = MagicMock(id="sub-1", tier="GROWTH", price_id="price-growth", amount=Decimal("200.00"), scheduled_tier=None)

    db = _db([
        _result(fetchone=payment),       # SELECT payments FOR UPDATE
        _result(),                       # UPDATE payments
        _result(fetchone=line_item),     # SELECT payment_line_items JOIN package_prices
        _result(fetchone=subscription),  # SELECT subscriptions FOR UPDATE
        _result(),                       # UPDATE subscriptions (period/status only)
        _result(),                       # UPDATE tenants contract dates
        _result(fetchall=[]),            # SELECT payment_line_items (ADDON) -> none
    ])

    out = await mark_paid(db, "payment-1", provider="MANUAL")
    assert out["already_paid"] is False

    update_subscriptions_call = db.execute.call_args_list[4]
    sql_text = str(update_subscriptions_call.args[0])
    params = update_subscriptions_call.args[1]
    assert "price_id" not in sql_text  # price/amount left untouched — tier mismatch guard
    assert params["sid"] == "sub-1"


async def test_mark_paid_reads_package_line_only_and_updates_addon_snapshots() -> None:
    """mark_paid's price-adoption read must be scoped to item_type='PACKAGE'
    (S10 fix — a payment can now also carry ADDON lines, which must never be
    mistaken for the package line), and separately updates each ACTIVE
    PURCHASED tenant_addons row to the ADDON line item's price snapshot."""
    payment = _payment(status="PENDING")
    package_line = MagicMock(price_id="price-1", amount=Decimal("200.00"), price_tier="GROWTH")
    subscription = MagicMock(id="sub-1", tier="GROWTH", price_id="price-1", scheduled_tier=None)
    addon_line = MagicMock(addon_code="LOGISTICS", addon_price_id="addon-price-NEW", amount=Decimal("60.00"))

    db = _db([
        _result(fetchone=payment),            # SELECT payments FOR UPDATE
        _result(),                            # UPDATE payments
        _result(fetchone=package_line),       # SELECT payment_line_items (PACKAGE)
        _result(fetchone=subscription),       # SELECT subscriptions FOR UPDATE
        _result(),                            # UPDATE subscriptions
        _result(),                            # UPDATE tenants contract dates
        _result(fetchall=[addon_line]),       # SELECT payment_line_items (ADDON)
        _result(),                            # UPDATE tenant_addons (LOGISTICS snapshot)
    ])

    out = await mark_paid(db, "payment-1", provider="MANUAL")
    assert out["already_paid"] is False

    package_line_call = db.execute.call_args_list[2]
    assert "item_type = 'PACKAGE'" in str(package_line_call.args[0])

    addon_lines_call = db.execute.call_args_list[6]
    assert "item_type = 'ADDON'" in str(addon_lines_call.args[0])

    addon_update_call = db.execute.call_args_list[7]
    sql_text = str(addon_update_call.args[0])
    params = addon_update_call.args[1]
    assert "UPDATE tenant_addons" in sql_text
    assert params["code"] == "LOGISTICS"
    assert params["price_id"] == "addon-price-NEW"
    assert params["amount"] == Decimal("60.00")


async def test_mark_paid_scheduled_tier_match_switches_tier_and_clears_schedule() -> None:
    """S13: the renewal PERIOD invoice's line item is priced at
    scheduled_tier -> paying it switches tier, adopts the new price,
    clears the schedule, and re-applies the package catalog."""
    import shared.billing.payments as payments_module

    payment = _payment(status="PENDING")
    line_item = MagicMock(price_id="price-starter", amount=Decimal("100.00"), price_tier="STARTER")
    subscription = MagicMock(id="sub-1", tier="GROWTH", price_id="price-growth", scheduled_tier="STARTER")

    db = _db([
        _result(fetchone=payment),       # SELECT payments FOR UPDATE
        _result(),                       # UPDATE payments
        _result(fetchone=line_item),     # SELECT payment_line_items (PACKAGE)
        _result(fetchone=subscription),  # SELECT subscriptions FOR UPDATE
        _result(),                       # UPDATE subscriptions (downgrade switch)
        _result(),                       # UPDATE tenants contract dates
        _result(fetchall=[]),            # SELECT payment_line_items (ADDON) -> none
    ])

    with patch.object(payments_module, "apply_package_to_tenant", AsyncMock()) as mock_apply:
        out = await mark_paid(db, "payment-1", provider="MANUAL")

    assert out["downgrade_applied"] == "STARTER"
    mock_apply.assert_awaited_once_with(db, payment.tenant_id, "STARTER")

    update_subscriptions_call = db.execute.call_args_list[4]
    sql_text = str(update_subscriptions_call.args[0])
    params = update_subscriptions_call.args[1]
    assert "tier = :tier" in sql_text
    assert "scheduled_tier = NULL" in sql_text
    assert params["tier"] == "STARTER"
    assert params["price_id"] == "price-starter"
    assert params["amount"] == Decimal("100.00")


async def test_mark_paid_scheduled_tier_mismatch_old_tier_invoice_no_switch() -> None:
    """A PENDING PERIOD invoice raised BEFORE the downgrade was scheduled is
    still priced at the OLD tier — paying it must not switch anything."""
    payment = _payment(status="PENDING")
    line_item = MagicMock(price_id="price-growth", amount=Decimal("200.00"), price_tier="GROWTH")
    subscription = MagicMock(id="sub-1", tier="GROWTH", price_id="price-growth", scheduled_tier="STARTER")

    db = _db([
        _result(fetchone=payment),       # SELECT payments FOR UPDATE
        _result(),                       # UPDATE payments
        _result(fetchone=line_item),     # SELECT payment_line_items (PACKAGE)
        _result(fetchone=subscription),  # SELECT subscriptions FOR UPDATE
        _result(),                       # UPDATE subscriptions (period/status only)
        _result(),                       # UPDATE tenants contract dates
        _result(fetchall=[]),            # SELECT payment_line_items (ADDON) -> none
    ])

    out = await mark_paid(db, "payment-1", provider="MANUAL")

    assert out["downgrade_applied"] is None
    update_subscriptions_call = db.execute.call_args_list[4]
    sql_text = str(update_subscriptions_call.args[0])
    assert "tier = :tier" not in sql_text  # the downgrade-switch branch was not taken


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
