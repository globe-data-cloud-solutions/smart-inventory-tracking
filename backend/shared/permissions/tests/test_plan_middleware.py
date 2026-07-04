"""Unit tests for plan_middleware — feature flag and resource limit checks."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from shared.permissions.plan_middleware import (
    check_plan,
    check_plan_create_user,
    check_plan_create_warehouse,
)

TENANT_ID = "aabbccdd-0000-0000-0000-000000000001"


def _user(role: str = "WM", tenant_id: str | None = TENANT_ID) -> MagicMock:
    u = MagicMock()
    u.role = role
    u.tenant_id = tenant_id
    return u


def _plan_result(
    plan_tier: str = "GROWTH",
    feature_flags: dict | None = None,
    max_warehouses: int | None = None,
    max_users: int | None = None,
) -> MagicMock:
    row = MagicMock()
    row.plan_tier = plan_tier
    row.feature_flags = feature_flags or {}
    row.sku_cap = None
    row.max_warehouses = max_warehouses
    row.max_users = max_users
    result = MagicMock()
    result.fetchone.return_value = row
    return result


def _db_plan_only(plan_result: MagicMock) -> AsyncMock:
    """DB mock that only needs one execute call (plan fetch, no count)."""
    db = AsyncMock()
    db.execute.return_value = plan_result
    return db


def _db_plan_then_count(plan_result: MagicMock, count: int) -> AsyncMock:
    """DB mock for three execute calls: plan fetch, tenant FOR UPDATE lock, COUNT(*)."""
    lock_result = MagicMock()
    count_result = MagicMock()
    count_result.scalar.return_value = count
    db = AsyncMock()
    db.execute.side_effect = [plan_result, lock_result, count_result]
    return db


# ── SA / TA bypass ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sa_bypasses_feature_flag_check() -> None:
    db = AsyncMock()
    await check_plan(_user(role="SA"), "transfer:create_sister", db)
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_ta_bypasses_feature_flag_check() -> None:
    db = AsyncMock()
    await check_plan(_user(role="TA"), "transfer:create_sister", db)
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_sa_bypasses_warehouse_limit() -> None:
    db = AsyncMock()
    await check_plan_create_warehouse(_user(role="SA"), db)
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_ta_bypasses_user_limit() -> None:
    db = AsyncMock()
    await check_plan_create_user(_user(role="TA"), db)
    db.execute.assert_not_called()


# ── tenant_id None → SA platform action bypass ────────────────────────────────

@pytest.mark.asyncio
async def test_no_tenant_id_bypasses_all_checks() -> None:
    db = AsyncMock()
    await check_plan(_user(role="NM", tenant_id=None), "transfer:create_sister", db)
    db.execute.assert_not_called()


# ── Feature flag False → 402 ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_feature_flag_false_raises_402() -> None:
    plan = _plan_result(
        plan_tier="GROWTH",
        feature_flags={"TRANSFERS_SISTER": False},
    )
    db = _db_plan_only(plan)

    with pytest.raises(HTTPException) as exc_info:
        await check_plan(_user(), "transfer:create_sister", db)

    assert exc_info.value.status_code == 402
    detail = exc_info.value.detail
    assert detail["code"] == "FEATURE_NOT_IN_PLAN"
    assert detail["feature"] == "TRANSFERS_SISTER"
    assert detail["plan_tier"] == "GROWTH"
    assert detail["upgrade_to"] == "ENTERPRISE"


# ── Feature flag True → passes ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_feature_flag_true_passes() -> None:
    plan = _plan_result(
        plan_tier="ENTERPRISE",
        feature_flags={"TRANSFERS_SISTER": True},
    )
    db = _db_plan_only(plan)
    # Should not raise
    await check_plan(_user(), "transfer:create_sister", db)


# ── Action with no flag mapping → always passes ───────────────────────────────

@pytest.mark.asyncio
async def test_unmapped_action_passes_regardless_of_flags() -> None:
    plan = _plan_result(feature_flags={})
    db = _db_plan_only(plan)
    # "inventory:receive" has no entry in ACTION_FLAG_MAP
    await check_plan(_user(), "inventory:receive", db)


# ── Warehouse limit reached → 402 ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_warehouse_limit_reached_raises_402() -> None:
    plan = _plan_result(plan_tier="GROWTH", max_warehouses=30)
    db = _db_plan_then_count(plan, count=30)

    with pytest.raises(HTTPException) as exc_info:
        await check_plan_create_warehouse(_user(), db)

    assert exc_info.value.status_code == 402
    detail = exc_info.value.detail
    assert detail["code"] == "PLAN_LIMIT_REACHED"
    assert detail["resource"] == "warehouses"
    assert detail["current"] == 30
    assert detail["limit"] == 30


# ── Warehouse limit NULL → unlimited, passes ─────────────────────────────────

@pytest.mark.asyncio
async def test_warehouse_limit_null_passes() -> None:
    plan = _plan_result(plan_tier="ENTERPRISE", max_warehouses=None)
    db = _db_plan_only(plan)
    await check_plan_create_warehouse(_user(), db)
    # Only one execute call (plan fetch); count query never issued
    assert db.execute.call_count == 1


# ── User limit reached → 402 ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_user_limit_reached_raises_402() -> None:
    plan = _plan_result(plan_tier="GROWTH", max_users=50)
    db = _db_plan_then_count(plan, count=50)

    with pytest.raises(HTTPException) as exc_info:
        await check_plan_create_user(_user(), db)

    assert exc_info.value.status_code == 402
    detail = exc_info.value.detail
    assert detail["code"] == "PLAN_LIMIT_REACHED"
    assert detail["resource"] == "users"
    assert detail["current"] == 50
    assert detail["limit"] == 50


# ── User limit NULL → unlimited, passes ──────────────────────────────────────

@pytest.mark.asyncio
async def test_user_limit_null_passes() -> None:
    plan = _plan_result(plan_tier="ENTERPRISE", max_users=None)
    db = _db_plan_only(plan)
    await check_plan_create_user(_user(), db)
    assert db.execute.call_count == 1


# ── TA is subject to warehouse limit (not bypassed) ──────────────────────────

@pytest.mark.asyncio
async def test_ta_warehouse_limit_enforced() -> None:
    """TA must respect the tenant's warehouse cap (only SA is exempt)."""
    plan = _plan_result(plan_tier="STARTER", max_warehouses=3)
    db = _db_plan_then_count(plan, count=3)

    with pytest.raises(HTTPException) as exc_info:
        await check_plan_create_warehouse(_user(role="TA"), db)

    assert exc_info.value.status_code == 402
    assert exc_info.value.detail["code"] == "PLAN_LIMIT_REACHED"


@pytest.mark.asyncio
async def test_ta_warehouse_limit_under_cap_passes() -> None:
    """TA under the cap should pass (e.g. 2 non-L1 nodes, limit 3)."""
    plan = _plan_result(plan_tier="STARTER", max_warehouses=3)
    db = _db_plan_then_count(plan, count=2)
    await check_plan_create_warehouse(_user(role="TA"), db)


# ── SA still bypasses warehouse limit ────────────────────────────────────────

@pytest.mark.asyncio
async def test_sa_still_bypasses_warehouse_limit() -> None:
    """SA manages plans and is never subject to warehouse caps."""
    db = AsyncMock()
    await check_plan_create_warehouse(_user(role="SA"), db)
    db.execute.assert_not_called()
