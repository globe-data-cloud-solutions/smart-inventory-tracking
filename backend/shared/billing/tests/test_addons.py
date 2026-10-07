"""Unit tests for shared.billing.addons — grant_addon/cancel_addon.

Mocked session throughout (no real DB connection): db.execute is an AsyncMock
whose side_effect is the ordered list of results the production code expects
for each await db.execute(...) call, in call order (same pattern as
test_payments.py)."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from shared.billing.addons import cancel_addon, grant_addon

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


def _addon(code="LOGISTICS", is_active=True) -> MagicMock:
    row = MagicMock()
    row.code, row.display_name, row.is_active = code, "Logistics & Fleet Management", is_active
    return row


# ── grant_addon — validation ordering ──────────────────────────────────────────

async def test_grant_invalid_source_raises_before_any_db_call() -> None:
    db = _db([])
    with pytest.raises(ValueError, match="INVALID_SOURCE"):
        await grant_addon(db, "tenant-1", "LOGISTICS", "FREE")
    db.execute.assert_not_called()


async def test_grant_unknown_addon_raises() -> None:
    db = _db([_result(fetchone=None)])  # _get_addon -> None
    with pytest.raises(ValueError, match="ADDON_NOT_FOUND"):
        await grant_addon(db, "tenant-1", "NOT_REAL", "OVERRIDE", note="x")


async def test_grant_inactive_addon_raises() -> None:
    db = _db([_result(fetchone=_addon(is_active=False))])
    with pytest.raises(ValueError, match="ADDON_INACTIVE"):
        await grant_addon(db, "tenant-1", "LOGISTICS", "OVERRIDE", note="x")


async def test_grant_feature_already_in_package_raises() -> None:
    tenant_row = MagicMock(plan_tier="ENTERPRISE")
    package_row = MagicMock(feature_flags={"LOGISTICS": True})
    db = _db([
        _result(fetchone=_addon()),       # _get_addon
        _result(fetchone=tenant_row),     # tenant plan_tier
        _result(fetchone=package_row),    # platform_tier_config.feature_flags
    ])
    with pytest.raises(ValueError, match="FEATURE_ALREADY_IN_PACKAGE"):
        await grant_addon(db, "tenant-1", "LOGISTICS", "OVERRIDE", note="x")


async def test_grant_already_active_raises() -> None:
    tenant_row = MagicMock(plan_tier="STARTER")
    package_row = MagicMock(feature_flags={"LOGISTICS": False})
    db = _db([
        _result(fetchone=_addon()),
        _result(fetchone=tenant_row),
        _result(fetchone=package_row),
        _result(fetchone=MagicMock()),    # existing ACTIVE tenant_addons row
    ])
    with pytest.raises(ValueError, match="ADDON_ALREADY_ACTIVE"):
        await grant_addon(db, "tenant-1", "LOGISTICS", "OVERRIDE", note="x")


# ── grant_addon — OVERRIDE ──────────────────────────────────────────────────────

async def test_grant_override_requires_note() -> None:
    tenant_row = MagicMock(plan_tier="STARTER")
    package_row = MagicMock(feature_flags={"LOGISTICS": False})
    db = _db([
        _result(fetchone=_addon()),
        _result(fetchone=tenant_row),
        _result(fetchone=package_row),
        _result(fetchone=None),  # no existing active grant
    ])
    with pytest.raises(ValueError, match="NOTE_REQUIRED"):
        await grant_addon(db, "tenant-1", "LOGISTICS", "OVERRIDE", note="   ")


async def test_grant_override_succeeds_amount_zero() -> None:
    tenant_row = MagicMock(plan_tier="STARTER")
    package_row = MagicMock(feature_flags={"LOGISTICS": False})
    db = _db([
        _result(fetchone=_addon()),
        _result(fetchone=tenant_row),
        _result(fetchone=package_row),
        _result(fetchone=None),
        _result(scalar_one="ta-1"),  # INSERT tenant_addons RETURNING id
    ])

    out = await grant_addon(db, "tenant-1", "LOGISTICS", "OVERRIDE", note="pilot customer", created_by="sa-1")

    assert out == {
        "id": "ta-1", "tenant_id": "tenant-1", "addon_code": "LOGISTICS",
        "source": "OVERRIDE", "status": "ACTIVE", "amount": Decimal("0"), "price_id": None,
    }
    insert_call = db.execute.call_args_list[4]
    params = insert_call.args[1]
    assert params["amount"] == Decimal("0")
    assert params["price_id"] is None
    assert params["note"] == "pilot customer"


# ── grant_addon — PURCHASED ──────────────────────────────────────────────────────

async def test_grant_purchased_no_live_subscription_raises() -> None:
    tenant_row = MagicMock(plan_tier="STARTER")
    package_row = MagicMock(feature_flags={"LOGISTICS": False})
    db = _db([
        _result(fetchone=_addon()),
        _result(fetchone=tenant_row),
        _result(fetchone=package_row),
        _result(fetchone=None),   # no existing active grant
        _result(fetchone=None),   # _get_live_subscription -> None
    ])
    with pytest.raises(ValueError, match="NO_LIVE_SUBSCRIPTION"):
        await grant_addon(db, "tenant-1", "LOGISTICS", "PURCHASED")


async def test_grant_purchased_no_price_available_raises() -> None:
    tenant_row = MagicMock(plan_tier="STARTER")
    package_row = MagicMock(feature_flags={"LOGISTICS": False})
    subscription = MagicMock(id="sub-1", billing_period="MONTHLY")
    db = _db([
        _result(fetchone=_addon()),
        _result(fetchone=tenant_row),
        _result(fetchone=package_row),
        _result(fetchone=None),
        _result(fetchone=subscription),
        _result(fetchone=None),   # get_current_addon_price -> None
    ])
    with pytest.raises(ValueError, match="ADDON_PRICE_NOT_AVAILABLE"):
        await grant_addon(db, "tenant-1", "LOGISTICS", "PURCHASED")


async def test_grant_purchased_succeeds_with_price_snapshot() -> None:
    tenant_row = MagicMock(plan_tier="STARTER")
    package_row = MagicMock(feature_flags={"LOGISTICS": False})
    subscription = MagicMock(id="sub-1", billing_period="MONTHLY")
    price_row = MagicMock(id="addon-price-1", amount=Decimal("50.00"))
    db = _db([
        _result(fetchone=_addon()),
        _result(fetchone=tenant_row),
        _result(fetchone=package_row),
        _result(fetchone=None),
        _result(fetchone=subscription),
        _result(fetchone=price_row),
        _result(scalar_one="ta-2"),
    ])

    out = await grant_addon(db, "tenant-1", "LOGISTICS", "PURCHASED", created_by="sa-1")

    assert out["source"] == "PURCHASED"
    assert out["amount"] == Decimal("50.00")
    assert out["price_id"] == "addon-price-1"


# ── cancel_addon ─────────────────────────────────────────────────────────────────

async def test_cancel_not_found_raises() -> None:
    db = _db([_result(fetchone=None)])
    with pytest.raises(ValueError, match="ADDON_GRANT_NOT_FOUND"):
        await cancel_addon(db, "tenant-1", "ta-1")


async def test_cancel_wrong_tenant_raises_not_found() -> None:
    """A grant belonging to a different tenant must 404 (never leak/act cross-tenant)."""
    row = MagicMock(id="ta-1", tenant_id="other-tenant", status="ACTIVE", addon_code="LOGISTICS")
    db = _db([_result(fetchone=row)])
    with pytest.raises(ValueError, match="ADDON_GRANT_NOT_FOUND"):
        await cancel_addon(db, "tenant-1", "ta-1")


async def test_cancel_already_cancelled_raises() -> None:
    row = MagicMock(id="ta-1", tenant_id="tenant-1", status="CANCELLED", addon_code="LOGISTICS")
    db = _db([_result(fetchone=row)])
    with pytest.raises(ValueError, match="ADDON_NOT_ACTIVE"):
        await cancel_addon(db, "tenant-1", "ta-1")


async def test_cancel_active_succeeds() -> None:
    row = MagicMock(id="ta-1", tenant_id="tenant-1", status="ACTIVE", addon_code="LOGISTICS")
    db = _db([_result(fetchone=row), _result()])

    out = await cancel_addon(db, "tenant-1", "ta-1", cancelled_by="sa-1")

    assert out == {"id": "ta-1", "addon_code": "LOGISTICS", "status": "CANCELLED"}
    update_call = db.execute.call_args_list[1]
    assert "CANCELLED" in str(update_call.args[0])
