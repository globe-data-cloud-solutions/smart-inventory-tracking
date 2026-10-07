"""Unit tests for shared.billing.proration (S11) — mid-period proration for
ANNUAL upgrades and PURCHASED add-ons.

Pure month-boundary math (remaining_billing_months, prorate, _add_months) is
tested directly, with no mocking. The orchestration functions
(apply_plan_change_with_proration, apply_addon_grant_with_proration,
preview_upgrade, preview_addon) have their collaborators patched at module
level — each collaborator (update_live_subscription_tier, grant_addon,
remaining_billing_months, create_proration_invoice, ...) already has its own
direct tests (here or in test_payments.py / test_addons.py / test_subscriptions.py),
so these tests only verify the WIRING: is the right collaborator called with
the right arguments, in the right order, and is a ValueError raised before
any write when it should be. create_proration_invoice itself is tested with
a mocked DB session (no real connection) and a patched _free_until so the
test is independent of the actual calendar date.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import shared.billing.proration as proration
from shared.billing.payments import mark_paid
from shared.billing.proration import ProrationLine, prorate, remaining_billing_months


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


def _sub(
    *, id="sub-1", tier="STARTER", billing_period="ANNUAL", status="ACTIVE",
    provider="MANUAL", price_id="price-starter", amount=Decimal("1000.00"), currency="ETB",
    current_period_start=date(2026, 1, 15), current_period_end=date(2027, 1, 15),
) -> MagicMock:
    row = MagicMock()
    row.id, row.tier, row.billing_period, row.status = id, tier, billing_period, status
    row.provider, row.price_id, row.amount, row.currency = provider, price_id, amount, currency
    row.current_period_start, row.current_period_end = current_period_start, current_period_end
    return row


# ── remaining_billing_months / prorate — pure, no mocking ───────────────────

def test_remaining_months_mid_period_example_is_7() -> None:
    """The decided worked example: annual period 2026-01-15 -> 2027-01-15,
    change on 2026-06-03 -> free 06-03 -> 06-15; 7 whole months remain."""
    assert remaining_billing_months(date(2026, 1, 15), date(2027, 1, 15), date(2026, 6, 3)) == 7


def test_remaining_months_on_the_boundary_day_itself_is_6() -> None:
    """On the boundary day itself (2026-06-15), the boundary is treated as
    the START of a new free billing month, not the end of the previous
    paid one — the next boundary 'strictly after today' is 07-15, not
    06-15 itself, so 6 whole months remain (not 7)."""
    assert remaining_billing_months(date(2026, 1, 15), date(2027, 1, 15), date(2026, 6, 15)) == 6


def test_remaining_months_last_billing_month_is_0() -> None:
    assert remaining_billing_months(date(2026, 1, 15), date(2027, 1, 15), date(2026, 12, 20)) == 0


def test_remaining_months_monthly_period_always_0() -> None:
    # A MONTHLY period: start -> start + 1 month. Only ever 1 billing month,
    # which is always the free one -- regardless of where `today` falls.
    assert remaining_billing_months(date(2026, 6, 6), date(2026, 7, 6), date(2026, 6, 6)) == 0
    assert remaining_billing_months(date(2026, 6, 6), date(2026, 7, 6), date(2026, 7, 5)) == 0


def test_remaining_months_jan_31_start_clamps_without_drift() -> None:
    """A Jan-31 annual start clamps its first boundary to Feb 28 (2026 is
    not a leap year), but the 12th absolute boundary still lands exactly on
    the real current_period_end (2027-01-31) — proving _add_months is
    absolute-from-start, not cumulative (cumulative stepping would drift
    the clamped day down to 28 and never recover it)."""
    start, end = date(2026, 1, 31), date(2027, 1, 31)
    assert proration._add_months(start, 1) == date(2026, 2, 28)
    assert proration._add_months(start, 12) == end
    assert proration._billing_months_in_period(start, end) == 12
    # Mid-period (today = 2026-07-15, well into billing month index 5 [Jul 31 start]).
    assert remaining_billing_months(start, end, date(2026, 7, 20)) == 6


def test_remaining_months_feb_29_leap_start() -> None:
    """A Feb-29 (leap year) annual start clamps its 12th boundary to Feb 28
    the following (non-leap) year, matching subscriptions.period_end()."""
    start, end = date(2028, 2, 29), date(2029, 2, 28)
    assert proration._add_months(start, 12) == end
    assert proration._billing_months_in_period(start, end) == 12
    assert remaining_billing_months(start, end, date(2028, 2, 29)) == 11


def test_prorate_2200_minus_1000_over_7_months_is_700() -> None:
    assert prorate(Decimal("2200.00") - Decimal("1000.00"), 7) == Decimal("700.00")


def test_prorate_rounds_half_up() -> None:
    assert prorate(Decimal("1000"), 5) == Decimal("416.67")


# ── create_proration_invoice — mocked DB, patched _free_until ───────────────

async def test_create_proration_invoice_zero_subtotal_writes_nothing() -> None:
    db = _db([])
    out = await proration.create_proration_invoice(
        db, "tenant-1", _sub(), [ProrationLine("PACKAGE", "GROWTH", "x", Decimal("0"))],
        "reason", "user-1",
    )
    assert out is None
    db.execute.assert_not_called()


async def test_create_proration_invoice_upgrade_700_plus_105_vat_is_805() -> None:
    sub = _sub(id="sub-1", provider="MANUAL", currency="ETB", current_period_end=date(2027, 1, 15))
    line = ProrationLine(
        item_type="PACKAGE", item_key="GROWTH", description="Upgrade STARTER -> GROWTH",
        amount=Decimal("700.00"), price_id="price-growth",
    )
    db = _db([
        _result(scalar_one="payment-prorate-1"),  # INSERT payments RETURNING id
        _result(),                                  # INSERT payment_line_items
    ])
    with patch.object(proration, "_free_until", return_value=date(2026, 6, 15)):
        out = await proration.create_proration_invoice(db, "tenant-1", sub, [line], "Upgrade", "user-1")

    assert out["subtotal"] == Decimal("700.00")
    assert out["vat_amount"] == Decimal("105.00")
    assert out["total"] == Decimal("805.00")
    assert out["invoice_kind"] == "PRORATION"
    assert out["period_start"] == date(2026, 6, 15)
    assert out["period_end"] == date(2027, 1, 15)

    insert_payment_call = db.execute.call_args_list[0]
    sql_text, params = str(insert_payment_call.args[0]), insert_payment_call.args[1]
    assert "invoice_kind" in sql_text and "'PRORATION'" in sql_text
    assert params["start"] == date(2026, 6, 15)
    assert params["end"] == date(2027, 1, 15)

    insert_line_call = db.execute.call_args_list[1]
    line_params = insert_line_call.args[1]
    assert line_params["price_id"] == "price-growth"
    assert line_params["addon_price_id"] is None
    assert line_params["amount"] == Decimal("700.00")


# ── apply_plan_change_with_proration — collaborators patched ───────────────

async def test_apply_plan_change_upgrade_annual_paid_raises_proration_invoice() -> None:
    sub_before = _sub(tier="STARTER", billing_period="ANNUAL", status="ACTIVE", amount=Decimal("1000.00"))
    new_price = MagicMock(id="price-growth", amount=Decimal("2200.00"))
    subscription_change = {
        "old_tier": "STARTER", "new_tier": "GROWTH",
        "old_amount": Decimal("1000.00"), "new_amount": Decimal("2200.00"),
    }
    expected_invoice = {"payment_id": "pay-1", "total": Decimal("805.00")}

    with patch.object(proration, "_get_live_subscription", AsyncMock(return_value=sub_before)), \
         patch.object(proration, "get_current_price", AsyncMock(return_value=new_price)), \
         patch.object(proration, "_has_pending_period_invoice", AsyncMock(return_value=False)), \
         patch.object(proration, "update_live_subscription_tier", AsyncMock(return_value=subscription_change)) as mock_update, \
         patch.object(proration, "_never_paid", AsyncMock(return_value=False)), \
         patch.object(proration, "remaining_billing_months", MagicMock(return_value=7)), \
         patch.object(proration, "create_proration_invoice", AsyncMock(return_value=expected_invoice)) as mock_create:
        out = await proration.apply_plan_change_with_proration(
            AsyncMock(), "tenant-1", "GROWTH", recorded_by="user-1",
        )

    mock_update.assert_awaited_once()
    assert out["subscription_change"] == subscription_change
    assert out["proration_invoice"] == expected_invoice

    mock_create.assert_awaited_once()
    lines = mock_create.call_args.args[3]
    assert len(lines) == 1
    assert lines[0].item_type == "PACKAGE"
    assert lines[0].amount == Decimal("700.00")  # prorate(2200-1000, 7)
    assert lines[0].price_id == "price-growth"


async def test_apply_plan_change_blocked_by_pending_period_invoice_raises_before_any_write() -> None:
    sub_before = _sub(tier="STARTER", amount=Decimal("1000.00"))
    new_price = MagicMock(id="price-growth", amount=Decimal("2200.00"))

    with patch.object(proration, "_get_live_subscription", AsyncMock(return_value=sub_before)), \
         patch.object(proration, "get_current_price", AsyncMock(return_value=new_price)), \
         patch.object(proration, "_has_pending_period_invoice", AsyncMock(return_value=True)), \
         patch.object(proration, "update_live_subscription_tier", AsyncMock()) as mock_update, \
         patch.object(proration, "create_proration_invoice", AsyncMock()) as mock_create:
        with pytest.raises(ValueError, match="INVOICE_PENDING_SETTLE_FIRST"):
            await proration.apply_plan_change_with_proration(
                AsyncMock(), "tenant-1", "GROWTH", recorded_by="user-1",
            )

    mock_update.assert_not_called()
    mock_create.assert_not_called()


async def test_apply_plan_change_downgrade_no_invoice_no_credit() -> None:
    sub_before = _sub(tier="GROWTH", amount=Decimal("2200.00"))
    cheaper_price = MagicMock(id="price-starter", amount=Decimal("1000.00"))
    subscription_change = {
        "old_tier": "GROWTH", "new_tier": "STARTER",
        "old_amount": Decimal("2200.00"), "new_amount": Decimal("1000.00"),
    }

    with patch.object(proration, "_get_live_subscription", AsyncMock(return_value=sub_before)), \
         patch.object(proration, "get_current_price", AsyncMock(return_value=cheaper_price)), \
         patch.object(proration, "_has_pending_period_invoice", AsyncMock()) as mock_pending, \
         patch.object(proration, "update_live_subscription_tier", AsyncMock(return_value=subscription_change)), \
         patch.object(proration, "create_proration_invoice", AsyncMock()) as mock_create:
        out = await proration.apply_plan_change_with_proration(
            AsyncMock(), "tenant-1", "STARTER", recorded_by="user-1",
        )

    mock_pending.assert_not_called()  # downgrade is never blocked -> never even checked
    mock_create.assert_not_called()
    assert out["proration_invoice"] is None


async def test_apply_plan_change_monthly_upgrade_no_invoice() -> None:
    sub_before = _sub(tier="STARTER", billing_period="MONTHLY", amount=Decimal("100.00"))
    new_price = MagicMock(id="price-growth-m", amount=Decimal("200.00"))
    subscription_change = {
        "old_tier": "STARTER", "new_tier": "GROWTH",
        "old_amount": Decimal("100.00"), "new_amount": Decimal("200.00"),
    }

    with patch.object(proration, "_get_live_subscription", AsyncMock(return_value=sub_before)), \
         patch.object(proration, "get_current_price", AsyncMock(return_value=new_price)), \
         patch.object(proration, "_has_pending_period_invoice", AsyncMock(return_value=False)), \
         patch.object(proration, "update_live_subscription_tier", AsyncMock(return_value=subscription_change)), \
         patch.object(proration, "create_proration_invoice", AsyncMock()) as mock_create:
        out = await proration.apply_plan_change_with_proration(
            AsyncMock(), "tenant-1", "GROWTH", recorded_by="user-1",
        )

    mock_create.assert_not_called()
    assert out["proration_invoice"] is None


async def test_apply_plan_change_never_paid_subscription_no_invoice() -> None:
    sub_before = _sub(tier="STARTER", billing_period="ANNUAL", status="PENDING_PAYMENT", amount=Decimal("1000.00"))
    new_price = MagicMock(id="price-growth", amount=Decimal("2200.00"))
    subscription_change = {
        "old_tier": "STARTER", "new_tier": "GROWTH",
        "old_amount": Decimal("1000.00"), "new_amount": Decimal("2200.00"),
    }

    with patch.object(proration, "_get_live_subscription", AsyncMock(return_value=sub_before)), \
         patch.object(proration, "get_current_price", AsyncMock(return_value=new_price)), \
         patch.object(proration, "_has_pending_period_invoice", AsyncMock(return_value=False)), \
         patch.object(proration, "update_live_subscription_tier", AsyncMock(return_value=subscription_change)), \
         patch.object(proration, "_never_paid", AsyncMock(return_value=True)), \
         patch.object(proration, "create_proration_invoice", AsyncMock()) as mock_create:
        out = await proration.apply_plan_change_with_proration(
            AsyncMock(), "tenant-1", "GROWTH", recorded_by="user-1",
        )

    mock_create.assert_not_called()
    assert out["proration_invoice"] is None


# ── apply_addon_grant_with_proration — collaborators patched ────────────────

async def test_apply_addon_grant_override_never_invoiced() -> None:
    grant_result = {"id": "ta-1", "addon_code": "LOGISTICS", "amount": Decimal("0"), "price_id": None}
    with patch.object(proration, "grant_addon", AsyncMock(return_value=grant_result)) as mock_grant, \
         patch.object(proration, "_has_pending_period_invoice", AsyncMock()) as mock_pending, \
         patch.object(proration, "create_proration_invoice", AsyncMock()) as mock_create:
        out = await proration.apply_addon_grant_with_proration(
            AsyncMock(), "tenant-1", "LOGISTICS", "OVERRIDE", note="pilot", created_by="sa-1",
        )

    mock_grant.assert_awaited_once()
    mock_pending.assert_not_called()
    mock_create.assert_not_called()
    assert out == {"grant": grant_result, "proration_invoice": None}


async def test_apply_addon_grant_purchased_annual_paid_raises_proration_invoice() -> None:
    grant_result = {"id": "ta-2", "addon_code": "LOGISTICS", "amount": Decimal("120.00"), "price_id": "addon-price-1"}
    sub = _sub(billing_period="ANNUAL", status="ACTIVE")
    expected_invoice = {"payment_id": "pay-2", "total": Decimal("80.50")}

    with patch.object(proration, "_has_pending_period_invoice", AsyncMock(return_value=False)), \
         patch.object(proration, "grant_addon", AsyncMock(return_value=grant_result)), \
         patch.object(proration, "_get_live_subscription", AsyncMock(return_value=sub)), \
         patch.object(proration, "_never_paid", AsyncMock(return_value=False)), \
         patch.object(proration, "remaining_billing_months", MagicMock(return_value=7)), \
         patch.object(proration, "create_proration_invoice", AsyncMock(return_value=expected_invoice)) as mock_create:
        out = await proration.apply_addon_grant_with_proration(
            AsyncMock(), "tenant-1", "LOGISTICS", "PURCHASED", created_by="sa-1",
        )

    assert out["proration_invoice"] == expected_invoice
    lines = mock_create.call_args.args[3]
    assert lines[0].item_type == "ADDON"
    assert lines[0].amount == Decimal("70.00")  # prorate(120.00, 7)
    assert lines[0].addon_price_id == "addon-price-1"


async def test_apply_addon_grant_purchased_blocked_before_grant() -> None:
    with patch.object(proration, "_has_pending_period_invoice", AsyncMock(return_value=True)), \
         patch.object(proration, "_get_live_subscription", AsyncMock(return_value=_sub())), \
         patch.object(proration, "grant_addon", AsyncMock()) as mock_grant:
        with pytest.raises(ValueError, match="INVOICE_PENDING_SETTLE_FIRST"):
            await proration.apply_addon_grant_with_proration(
                AsyncMock(), "tenant-1", "LOGISTICS", "PURCHASED", created_by="sa-1",
            )

    mock_grant.assert_not_called()


# ── preview_upgrade / preview_addon — read-only, collaborators patched ─────

async def test_preview_upgrade_no_live_subscription_returns_empty() -> None:
    with patch.object(proration, "_get_live_subscription", AsyncMock(return_value=None)):
        out = await proration.preview_upgrade(AsyncMock(), "tenant-1", "GROWTH")
    assert out["will_invoice"] is False
    assert out["blocked_code"] is None


async def test_preview_upgrade_blocked_by_pending_period_invoice() -> None:
    sub = _sub(amount=Decimal("1000.00"))
    new_price = MagicMock(amount=Decimal("2200.00"))
    with patch.object(proration, "_get_live_subscription", AsyncMock(return_value=sub)), \
         patch.object(proration, "get_current_price", AsyncMock(return_value=new_price)), \
         patch.object(proration, "_has_pending_period_invoice", AsyncMock(return_value=True)):
        out = await proration.preview_upgrade(AsyncMock(), "tenant-1", "GROWTH")
    assert out["will_invoice"] is False
    assert out["blocked_code"] == "INVOICE_PENDING_SETTLE_FIRST"


async def test_preview_upgrade_downgrade_no_charge_not_blocked() -> None:
    sub = _sub(amount=Decimal("2200.00"))
    cheaper_price = MagicMock(amount=Decimal("1000.00"))
    with patch.object(proration, "_get_live_subscription", AsyncMock(return_value=sub)), \
         patch.object(proration, "get_current_price", AsyncMock(return_value=cheaper_price)), \
         patch.object(proration, "_has_pending_period_invoice", AsyncMock()) as mock_pending:
        out = await proration.preview_upgrade(AsyncMock(), "tenant-1", "STARTER")
    mock_pending.assert_not_called()
    assert out["will_invoice"] is False
    assert out["blocked_code"] is None


async def test_preview_upgrade_annual_paid_mid_period_shows_amounts() -> None:
    sub = _sub(billing_period="ANNUAL", status="ACTIVE", amount=Decimal("1000.00"))
    new_price = MagicMock(amount=Decimal("2200.00"))
    with patch.object(proration, "_get_live_subscription", AsyncMock(return_value=sub)), \
         patch.object(proration, "get_current_price", AsyncMock(return_value=new_price)), \
         patch.object(proration, "_has_pending_period_invoice", AsyncMock(return_value=False)), \
         patch.object(proration, "_never_paid", AsyncMock(return_value=False)), \
         patch.object(proration, "remaining_billing_months", MagicMock(return_value=7)), \
         patch.object(proration, "_free_until", MagicMock(return_value=date(2026, 6, 15))):
        out = await proration.preview_upgrade(AsyncMock(), "tenant-1", "GROWTH")

    assert out["will_invoice"] is True
    assert out["remaining_months"] == 7
    assert out["subtotal"] == Decimal("700.00")
    assert out["vat"] == Decimal("105.00")
    assert out["total"] == Decimal("805.00")
    assert out["free_until"] == date(2026, 6, 15)


async def test_preview_addon_purchased_annual_shows_amounts() -> None:
    sub = _sub(billing_period="ANNUAL", status="ACTIVE")
    price = MagicMock(amount=Decimal("120.00"))
    with patch.object(proration, "_get_live_subscription", AsyncMock(return_value=sub)), \
         patch.object(proration, "get_current_addon_price", AsyncMock(return_value=price)), \
         patch.object(proration, "_has_pending_period_invoice", AsyncMock(return_value=False)), \
         patch.object(proration, "_never_paid", AsyncMock(return_value=False)), \
         patch.object(proration, "remaining_billing_months", MagicMock(return_value=7)), \
         patch.object(proration, "_free_until", MagicMock(return_value=date(2026, 6, 15))):
        out = await proration.preview_addon(AsyncMock(), "tenant-1", "LOGISTICS")

    assert out["will_invoice"] is True
    assert out["subtotal"] == Decimal("70.00")
    assert out["new_amount"] == Decimal("120.00")
    assert out["old_amount"] is None


# ── mark_paid(PRORATION) — never touches subscription/contract/tenant_addons ─

def _proration_payment(*, status="PENDING") -> MagicMock:
    row = MagicMock()
    row.id, row.tenant_id, row.subscription_id = "payment-prorate-1", "tenant-1", "sub-1"
    row.status, row.invoice_kind = status, "PRORATION"
    row.period_start, row.period_end = date(2026, 6, 15), date(2027, 1, 15)
    return row


async def test_mark_paid_proration_only_flips_status_nothing_else() -> None:
    payment = _proration_payment()
    db = _db([
        _result(fetchone=payment),  # SELECT payments FOR UPDATE
        _result(),                 # UPDATE payments
    ])

    out = await mark_paid(db, "payment-prorate-1", provider="MANUAL", recorded_by="sa-1")

    assert out == {"payment_id": "payment-prorate-1", "status": "PAID", "already_paid": False}
    assert db.execute.call_count == 2  # no subscription/tenant/tenant_addons queries at all
