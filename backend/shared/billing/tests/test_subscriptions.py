"""Unit tests for shared.billing.subscriptions — pure VAT math, period-end
calculation, and update_live_subscription_tier's plan-change contract (no
proration; current_period dates and contract dates untouched). The pure
functions need no DB; update_live_subscription_tier uses a mocked session."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from shared.billing.subscriptions import get_current_price, period_end, update_live_subscription_tier, vat_breakdown


def test_vat_breakdown_1000_annual() -> None:
    result = vat_breakdown(Decimal("1000"))
    assert result["subtotal"] == Decimal("1000")
    assert result["vat_amount"] == Decimal("150.00")
    assert result["total"] == Decimal("1150.00")


def test_vat_breakdown_100_monthly() -> None:
    result = vat_breakdown(Decimal("100"))
    assert result["vat_amount"] == Decimal("15.00")
    assert result["total"] == Decimal("115.00")


def test_period_end_monthly_clamps_jan_31() -> None:
    assert period_end(date(2026, 1, 31), "MONTHLY") == date(2026, 2, 28)  # 2026 not a leap year
    assert period_end(date(2028, 1, 31), "MONTHLY") == date(2028, 2, 29)  # 2028 is a leap year


def test_period_end_annual_clamps_leap_day() -> None:
    assert period_end(date(2028, 2, 29), "ANNUAL") == date(2029, 2, 28)


def test_period_end_normal_monthly_and_annual() -> None:
    assert period_end(date(2026, 6, 15), "MONTHLY") == date(2026, 7, 15)
    assert period_end(date(2026, 6, 15), "ANNUAL") == date(2027, 6, 15)


def test_period_end_december_wraps_to_next_year() -> None:
    assert period_end(date(2026, 12, 15), "MONTHLY") == date(2027, 1, 15)


def test_period_end_unknown_billing_period_raises() -> None:
    with pytest.raises(ValueError):
        period_end(date(2026, 1, 1), "WEEKLY")


@pytest.mark.asyncio
async def test_get_current_price_tie_break_on_created_at_favors_most_recent() -> None:
    """Prices are append-only, so correcting a wrong scheduled price means posting a
    new row with the SAME effective_from — the ORDER BY must break the tie on
    created_at DESC so the correcting (more recently created) row wins."""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(fetchone=MagicMock(return_value=MagicMock())))

    await get_current_price(db, "GROWTH", "MONTHLY")

    sql_text = str(db.execute.call_args.args[0])
    assert "ORDER BY effective_from DESC, created_at DESC" in sql_text


def _db(side_effect: list) -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=side_effect)
    return db


def _result(fetchone=None) -> MagicMock:
    result = MagicMock()
    result.fetchone = MagicMock(return_value=fetchone)
    return result


@pytest.mark.asyncio
async def test_update_live_subscription_tier_updates_tier_and_price() -> None:
    sub = MagicMock(id="sub-1", tier="GROWTH", billing_period="MONTHLY", amount=Decimal("200.00"))
    new_price = MagicMock(id="price-ent", amount=Decimal("500.00"))
    db = _db([
        _result(fetchone=sub),        # SELECT live subscription
        _result(fetchone=new_price),  # get_current_price()
        _result(),                    # UPDATE subscriptions
    ])

    out = await update_live_subscription_tier(db, "tenant-1", "ENTERPRISE")

    assert out == {
        "old_tier": "GROWTH", "new_tier": "ENTERPRISE",
        "old_amount": Decimal("200.00"), "new_amount": Decimal("500.00"),
    }
    update_call = db.execute.call_args_list[2]
    sql_text, params = str(update_call.args[0]), update_call.args[1]
    assert "UPDATE subscriptions" in sql_text
    assert params["tier"] == "ENTERPRISE"
    assert params["price_id"] == "price-ent"
    assert params["amount"] == Decimal("500.00")
    # Only tier/price/amount/updated_at are touched — never the period or
    # contract dates (no proration; those move only via mark_paid()).
    assert "current_period_start" not in sql_text
    assert "current_period_end" not in sql_text
    assert "contract_start" not in sql_text
    assert "contract_end" not in sql_text


@pytest.mark.asyncio
async def test_update_live_subscription_tier_no_live_subscription_returns_none() -> None:
    db = _db([_result(fetchone=None)])
    out = await update_live_subscription_tier(db, "tenant-1", "ENTERPRISE")
    assert out is None
    assert db.execute.call_count == 1  # no price lookup, no UPDATE


@pytest.mark.asyncio
async def test_update_live_subscription_tier_unchanged_tier_is_a_noop() -> None:
    sub = MagicMock(id="sub-1", tier="GROWTH", billing_period="MONTHLY", amount=Decimal("200.00"))
    db = _db([_result(fetchone=sub)])
    out = await update_live_subscription_tier(db, "tenant-1", "GROWTH")
    assert out is None
    assert db.execute.call_count == 1


@pytest.mark.asyncio
async def test_update_live_subscription_tier_no_price_raises() -> None:
    sub = MagicMock(id="sub-1", tier="GROWTH", billing_period="MONTHLY", amount=Decimal("200.00"))
    db = _db([_result(fetchone=sub), _result(fetchone=None)])
    with pytest.raises(ValueError, match="PRICE_NOT_AVAILABLE"):
        await update_live_subscription_tier(db, "tenant-1", "ENTERPRISE")
