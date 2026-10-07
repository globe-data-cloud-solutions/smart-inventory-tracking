"""Unit tests for shared.plans.catalog.get_tenant_entitlements — the S10
feature_flags-OR-active-add-ons merge, and the no-ENTERPRISE-fallback fix.

Mocked session throughout (no real DB connection): db.execute is an AsyncMock
whose side_effect is the ordered list of results the production code expects
for each await db.execute(...) call, in call order (same pattern as
test_payments.py)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from shared.plans.catalog import get_tenant_entitlements

pytestmark = pytest.mark.asyncio


def _db(side_effect: list) -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=side_effect)
    return db


def _result(fetchone=None, fetchall=None) -> MagicMock:
    result = MagicMock()
    result.fetchone = MagicMock(return_value=fetchone)
    result.fetchall = MagicMock(return_value=fetchall if fetchall is not None else [])
    return result


def _tenant_row(plan_tier="STARTER", feature_flags=None, sku_cap=None,
                 max_warehouses=None, max_users=None) -> MagicMock:
    row = MagicMock()
    row.plan_tier, row.feature_flags = plan_tier, feature_flags or {}
    row.sku_cap, row.max_warehouses, row.max_users = sku_cap, max_warehouses, max_users
    return row


async def test_no_such_tenant_returns_empty_dict() -> None:
    db = _db([_result(fetchone=None)])
    out = await get_tenant_entitlements(db, "unknown-tenant")
    assert out == {}


async def test_plan_tier_none_returns_none_not_enterprise() -> None:
    """The ENTERPRISE-fallback bug fix (S10): a tenant with no plan_tier set
    gets plan_tier=None, never a hardcoded tier."""
    db = _db([
        _result(fetchone=_tenant_row(plan_tier=None)),
        _result(fetchall=[]),
    ])
    out = await get_tenant_entitlements(db, "tenant-1")
    assert out["plan_tier"] is None


async def test_no_active_addons_feature_flags_unchanged() -> None:
    db = _db([
        _result(fetchone=_tenant_row(feature_flags={"LOGISTICS": False})),
        _result(fetchall=[]),
    ])
    out = await get_tenant_entitlements(db, "tenant-1")
    assert out["feature_flags"] == {"LOGISTICS": False}
    assert out["addons"] == []


async def test_active_addon_ors_flag_to_true() -> None:
    """A package flag that is False is overridden to True by an ACTIVE add-on
    grant — an add-on only ever adds, never removes, a package flag."""
    addon_row = MagicMock(addon_code="LOGISTICS")
    db = _db([
        _result(fetchone=_tenant_row(plan_tier="STARTER", feature_flags={"LOGISTICS": False})),
        _result(fetchall=[addon_row]),
    ])
    out = await get_tenant_entitlements(db, "tenant-1")
    assert out["feature_flags"]["LOGISTICS"] is True
    assert out["addons"] == ["LOGISTICS"]


async def test_addon_survives_plan_change() -> None:
    """apply_package_to_tenant() (a plan change) replaces tenants.feature_flags
    wholesale but never touches tenant_addons — so the SAME active grant keeps
    showing up after a tier switch, here simulated as a STARTER tenant (whose
    package does not include LOGISTICS) still carrying the add-on."""
    addon_row = MagicMock(addon_code="LOGISTICS")
    db = _db([
        # Before: GROWTH tenant, LOGISTICS already true from the package itself.
        _result(fetchone=_tenant_row(plan_tier="GROWTH", feature_flags={"LOGISTICS": True})),
        _result(fetchall=[addon_row]),
    ])
    before = await get_tenant_entitlements(db, "tenant-1")
    assert before["feature_flags"]["LOGISTICS"] is True

    db2 = _db([
        # After a downgrade to STARTER (package LOGISTICS=False), the SAME
        # tenant_addons row is still ACTIVE and still OR's the flag to True.
        _result(fetchone=_tenant_row(plan_tier="STARTER", feature_flags={"LOGISTICS": False})),
        _result(fetchall=[addon_row]),
    ])
    after = await get_tenant_entitlements(db2, "tenant-1")
    assert after["feature_flags"]["LOGISTICS"] is True
    assert after["addons"] == ["LOGISTICS"]


async def test_addon_query_filters_by_window_dates_in_sql() -> None:
    """The addon query's WHERE clause is the only place window dates
    (starts_on/ends_on) are enforced — assert the literal SQL conditions are
    present so a future edit can't silently drop them."""
    db = _db([
        _result(fetchone=_tenant_row()),
        _result(fetchall=[]),
    ])
    await get_tenant_entitlements(db, "tenant-1")

    addon_query_call = db.execute.call_args_list[1]
    sql_text = str(addon_query_call.args[0])
    assert "status = 'ACTIVE'" in sql_text
    assert "starts_on <= CURRENT_DATE" in sql_text
    assert "ends_on IS NULL OR ends_on >= CURRENT_DATE" in sql_text
