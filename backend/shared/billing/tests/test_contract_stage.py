"""Unit tests for shared.billing.contract_stage — pure stage boundaries."""
from __future__ import annotations

from datetime import date, datetime

from shared.billing.contract_stage import compute_contract_stage


def test_no_contract_end_is_active() -> None:
    assert compute_contract_stage(None, date(2026, 1, 1)) == "ACTIVE"


def test_15_days_before_end_is_active() -> None:
    end = date(2026, 1, 30)
    today = end.fromordinal(end.toordinal() - 15)
    assert compute_contract_stage(end, today) == "ACTIVE"


def test_14_days_before_end_is_expiring() -> None:
    end = date(2026, 1, 30)
    today = end.fromordinal(end.toordinal() - 14)
    assert compute_contract_stage(end, today) == "EXPIRING"


def test_end_date_itself_is_expiring() -> None:
    end = date(2026, 1, 30)
    assert compute_contract_stage(end, end) == "EXPIRING"


def test_1_day_past_end_is_grace() -> None:
    end = date(2026, 1, 30)
    today = end.fromordinal(end.toordinal() + 1)
    assert compute_contract_stage(end, today) == "GRACE"


def test_14_days_past_end_is_grace() -> None:
    end = date(2026, 1, 30)
    today = end.fromordinal(end.toordinal() + 14)
    assert compute_contract_stage(end, today) == "GRACE"


def test_15_days_past_end_is_read_only() -> None:
    end = date(2026, 1, 30)
    today = end.fromordinal(end.toordinal() + 15)
    assert compute_contract_stage(end, today) == "READ_ONLY"


def test_datetime_input_is_normalised_to_date() -> None:
    end = datetime(2026, 1, 30, 13, 45)
    today = date(2026, 1, 1)
    assert compute_contract_stage(end, today) == "ACTIVE"


def test_unexpected_type_falls_back_to_active_with_warning(caplog) -> None:
    with caplog.at_level("WARNING"):
        result = compute_contract_stage("2026-01-30", date(2026, 2, 20))  # type: ignore[arg-type]
    assert result == "ACTIVE"
    assert "unexpected contract_end type" in caplog.text
