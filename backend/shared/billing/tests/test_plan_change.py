"""Unit tests for shared.billing.plan_change (S13) — schedule a paid
downgrade for the next renewal, or apply any other plan change immediately.

Mocked session throughout, same style as test_proration.py: collaborators
(_get_live_subscription_for_update, get_current_price, apply_package_to_tenant,
apply_plan_change_with_proration, proration._never_paid) are patched at
module level — each already has its own direct tests — so these only verify
the WIRING and the branch decisions."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import shared.billing.plan_change as plan_change
import shared.billing.proration as proration
from shared.billing.plan_change import cancel_scheduled_downgrade, change_plan

pytestmark = pytest.mark.asyncio


def _sub(
    *,
    id="sub-1",
    tier="GROWTH",
    billing_period="ANNUAL",
    status="ACTIVE",
    amount=Decimal("2200.00"),
    scheduled_tier=None,
    current_period_start=date(2026, 1, 15),
    current_period_end=date(2027, 1, 15),
) -> MagicMock:
    row = MagicMock()
    row.id, row.tier, row.billing_period, row.status = id, tier, billing_period, status
    row.amount, row.scheduled_tier = amount, scheduled_tier
    row.current_period_start, row.current_period_end = current_period_start, current_period_end
    return row


def _price(*, id="price-1", amount=Decimal("1000.00")) -> MagicMock:
    return MagicMock(id=id, amount=amount)


# ── change_plan — SCHEDULE a paid downgrade ─────────────────────────────────


async def test_annual_paid_downgrade_renewal_is_scheduled_not_applied() -> None:
    sub = _sub(tier="GROWTH", billing_period="ANNUAL", amount=Decimal("2200.00"))
    cheaper_price = _price(amount=Decimal("1000.00"))

    with (
        patch.object(plan_change, "_get_live_subscription_for_update", AsyncMock(return_value=sub)),
        patch.object(plan_change, "get_current_price", AsyncMock(return_value=cheaper_price)),
        patch.object(proration, "_never_paid", AsyncMock(return_value=False)),
        patch.object(
            plan_change, "_find_pending_old_tier_period_invoice", AsyncMock(return_value=None)
        ),
        patch.object(plan_change, "apply_package_to_tenant", AsyncMock()) as mock_apply,
        patch.object(
            plan_change, "apply_plan_change_with_proration", AsyncMock()
        ) as mock_proration,
    ):
        db = AsyncMock()
        out = await change_plan(db, "tenant-1", "STARTER", recorded_by="sa-1")

    assert out["mode"] == "SCHEDULED"
    assert out["plan_tier"] == "GROWTH"
    assert out["scheduled_tier"] == "STARTER"
    assert out["effective_at"] == date(2027, 1, 15)
    assert out["pending_renewal_invoice_id"] is None
    mock_apply.assert_not_called()
    mock_proration.assert_not_called()

    schedule_update_call = db.execute.call_args_list[0]
    sql_text, params = str(schedule_update_call.args[0]), schedule_update_call.args[1]
    assert "scheduled_tier = :tier" in sql_text
    assert params["tier"] == "STARTER"
    assert params["by"] == "sa-1"


async def test_monthly_paid_downgrade_renewal_is_scheduled() -> None:
    sub = _sub(tier="GROWTH", billing_period="MONTHLY", amount=Decimal("200.00"))
    cheaper_price = _price(amount=Decimal("100.00"))

    with (
        patch.object(plan_change, "_get_live_subscription_for_update", AsyncMock(return_value=sub)),
        patch.object(plan_change, "get_current_price", AsyncMock(return_value=cheaper_price)),
        patch.object(proration, "_never_paid", AsyncMock(return_value=False)),
        patch.object(
            plan_change, "_find_pending_old_tier_period_invoice", AsyncMock(return_value=None)
        ),
        patch.object(plan_change, "apply_package_to_tenant", AsyncMock()) as mock_apply,
    ):
        db = AsyncMock()
        out = await change_plan(db, "tenant-1", "STARTER", recorded_by="sa-1")

    assert out["mode"] == "SCHEDULED"
    mock_apply.assert_not_called()


async def test_pending_old_tier_period_invoice_id_is_surfaced() -> None:
    sub = _sub(tier="GROWTH", amount=Decimal("2200.00"))
    cheaper_price = _price(amount=Decimal("1000.00"))

    with (
        patch.object(plan_change, "_get_live_subscription_for_update", AsyncMock(return_value=sub)),
        patch.object(plan_change, "get_current_price", AsyncMock(return_value=cheaper_price)),
        patch.object(proration, "_never_paid", AsyncMock(return_value=False)),
        patch.object(
            plan_change,
            "_find_pending_old_tier_period_invoice",
            AsyncMock(return_value="payment-old-1"),
        ),
    ):
        db = AsyncMock()
        out = await change_plan(db, "tenant-1", "STARTER", recorded_by="sa-1")

    assert out["pending_renewal_invoice_id"] == "payment-old-1"


async def test_cap_override_while_scheduling_raises() -> None:
    sub = _sub(tier="GROWTH", amount=Decimal("2200.00"))
    cheaper_price = _price(amount=Decimal("1000.00"))

    with (
        patch.object(plan_change, "_get_live_subscription_for_update", AsyncMock(return_value=sub)),
        patch.object(plan_change, "get_current_price", AsyncMock(return_value=cheaper_price)),
        patch.object(proration, "_never_paid", AsyncMock(return_value=False)),
        patch.object(plan_change, "apply_package_to_tenant", AsyncMock()) as mock_apply,
    ):
        db = AsyncMock()
        with pytest.raises(ValueError, match="CAP_OVERRIDE_NOT_ALLOWED_WHEN_SCHEDULING"):
            await change_plan(db, "tenant-1", "STARTER", recorded_by="sa-1", max_users=5)

    mock_apply.assert_not_called()
    db.execute.assert_not_called()  # no write at all before the raise


# ── change_plan — IMMEDIATE ──────────────────────────────────────────────────


async def test_effective_immediate_override_applies_now_and_clears_schedule() -> None:
    sub = _sub(tier="GROWTH", amount=Decimal("2200.00"), scheduled_tier="STARTER")
    cheaper_price = _price(amount=Decimal("1000.00"))
    effective_package = {"plan_tier": "STARTER", "max_warehouses": 2, "max_users": 5}
    proration_result = {"subscription_change": {"old_tier": "GROWTH"}, "proration_invoice": None}

    with (
        patch.object(plan_change, "_get_live_subscription_for_update", AsyncMock(return_value=sub)),
        patch.object(plan_change, "get_current_price", AsyncMock(return_value=cheaper_price)),
        patch.object(proration, "_never_paid", AsyncMock(return_value=False)),
        patch.object(
            plan_change, "apply_package_to_tenant", AsyncMock(return_value=effective_package)
        ) as mock_apply,
        patch.object(
            plan_change,
            "apply_plan_change_with_proration",
            AsyncMock(return_value=proration_result),
        ) as mock_proration,
    ):
        db = AsyncMock()
        out = await change_plan(
            db, "tenant-1", "STARTER", effective="IMMEDIATE", recorded_by="sa-1"
        )

    assert out["mode"] == "IMMEDIATE"
    assert out["effective"] == effective_package
    mock_apply.assert_awaited_once()
    mock_proration.assert_awaited_once()

    clear_call = db.execute.call_args_list[0]
    assert "scheduled_tier = NULL" in str(clear_call.args[0])


async def test_never_paid_downgrade_is_immediate() -> None:
    sub = _sub(tier="GROWTH", status="PENDING_PAYMENT", amount=Decimal("2200.00"))
    cheaper_price = _price(amount=Decimal("1000.00"))

    with (
        patch.object(plan_change, "_get_live_subscription_for_update", AsyncMock(return_value=sub)),
        patch.object(plan_change, "get_current_price", AsyncMock(return_value=cheaper_price)),
        patch.object(proration, "_never_paid", AsyncMock(return_value=True)),
        patch.object(
            plan_change, "apply_package_to_tenant", AsyncMock(return_value={})
        ) as mock_apply,
        patch.object(
            plan_change,
            "apply_plan_change_with_proration",
            AsyncMock(return_value={"subscription_change": None, "proration_invoice": None}),
        ),
    ):
        db = AsyncMock()
        out = await change_plan(db, "tenant-1", "STARTER", recorded_by="sa-1")

    assert out["mode"] == "IMMEDIATE"
    mock_apply.assert_awaited_once()


async def test_upgrade_while_scheduled_is_immediate_and_clears_schedule() -> None:
    sub = _sub(tier="STARTER", amount=Decimal("1000.00"), scheduled_tier="PREVIOUS_TIER")
    pricier = _price(amount=Decimal("2200.00"))

    with (
        patch.object(plan_change, "_get_live_subscription_for_update", AsyncMock(return_value=sub)),
        patch.object(plan_change, "get_current_price", AsyncMock(return_value=pricier)),
        patch.object(proration, "_never_paid", AsyncMock(return_value=False)),
        patch.object(
            plan_change, "apply_package_to_tenant", AsyncMock(return_value={})
        ) as mock_apply,
        patch.object(
            plan_change,
            "apply_plan_change_with_proration",
            AsyncMock(return_value={"subscription_change": None, "proration_invoice": None}),
        ),
    ):
        db = AsyncMock()
        out = await change_plan(db, "tenant-1", "GROWTH", recorded_by="sa-1")

    assert out["mode"] == "IMMEDIATE"
    mock_apply.assert_awaited_once()
    clear_call = db.execute.call_args_list[0]
    assert "scheduled_tier = NULL" in str(clear_call.args[0])


# ── change_plan — UNCHANGED ──────────────────────────────────────────────────


async def test_setting_current_tier_while_scheduled_clears_it_as_unchanged() -> None:
    sub = _sub(tier="GROWTH", scheduled_tier="STARTER")

    with patch.object(
        plan_change, "_get_live_subscription_for_update", AsyncMock(return_value=sub)
    ):
        db = AsyncMock()
        out = await change_plan(db, "tenant-1", "GROWTH", recorded_by="sa-1")

    assert out == {"mode": "UNCHANGED", "scheduled_cleared": True}
    clear_call = db.execute.call_args_list[0]
    assert "scheduled_tier = NULL" in str(clear_call.args[0])


async def test_setting_current_tier_with_nothing_scheduled_is_unchanged_no_write() -> None:
    sub = _sub(tier="GROWTH", scheduled_tier=None)

    with patch.object(
        plan_change, "_get_live_subscription_for_update", AsyncMock(return_value=sub)
    ):
        db = AsyncMock()
        out = await change_plan(db, "tenant-1", "GROWTH", recorded_by="sa-1")

    assert out == {"mode": "UNCHANGED", "scheduled_cleared": False}
    db.execute.assert_not_called()


# ── cancel_scheduled_downgrade ────────────────────────────────────────────────


async def test_cancel_scheduled_downgrade_clears_it() -> None:
    sub = _sub(tier="GROWTH", scheduled_tier="STARTER")

    with patch.object(
        plan_change, "_get_live_subscription_for_update", AsyncMock(return_value=sub)
    ):
        db = AsyncMock()
        out = await cancel_scheduled_downgrade(db, "tenant-1")

    assert out == {"cancelled_tier": "STARTER"}
    clear_call = db.execute.call_args_list[0]
    assert "scheduled_tier = NULL" in str(clear_call.args[0])


async def test_cancel_scheduled_downgrade_none_scheduled_raises() -> None:
    sub = _sub(tier="GROWTH", scheduled_tier=None)

    with patch.object(
        plan_change, "_get_live_subscription_for_update", AsyncMock(return_value=sub)
    ):
        db = AsyncMock()
        with pytest.raises(ValueError, match="NO_SCHEDULED_CHANGE"):
            await cancel_scheduled_downgrade(db, "tenant-1")


async def test_cancel_scheduled_downgrade_no_live_subscription_raises() -> None:
    with patch.object(
        plan_change, "_get_live_subscription_for_update", AsyncMock(return_value=None)
    ):
        db = AsyncMock()
        with pytest.raises(ValueError, match="NO_SCHEDULED_CHANGE"):
            await cancel_scheduled_downgrade(db, "tenant-1")


# ── INVALID_EFFECTIVE ─────────────────────────────────────────────────────────


async def test_invalid_effective_raises_before_any_read() -> None:
    db = AsyncMock()
    with pytest.raises(ValueError, match="INVALID_EFFECTIVE"):
        await change_plan(db, "tenant-1", "STARTER", effective="NEVER", recorded_by="sa-1")
    db.execute.assert_not_called()
