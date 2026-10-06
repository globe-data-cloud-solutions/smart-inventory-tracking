"""Unit tests for shared.billing.subscriptions — pure VAT math and
period-end calculation. No DB connection required."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from shared.billing.subscriptions import period_end, vat_breakdown


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
