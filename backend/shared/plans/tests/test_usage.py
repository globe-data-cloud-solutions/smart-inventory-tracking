"""Unit tests for shared.plans.usage — the counts used both for plan
enforcement (plan_middleware.py, product-service create_product) and for
GET /me/plan-usage display."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from shared.plans.usage import (
    count_active_skus,
    count_active_warehouses,
    count_billable_users,
    get_plan_usage,
)

TENANT_ID = "aabbccdd-0000-0000-0000-000000000001"


def _count_result(n: int) -> MagicMock:
    result = MagicMock()
    result.scalar.return_value = n
    return result


@pytest.mark.asyncio
async def test_count_active_skus() -> None:
    db = AsyncMock()
    db.execute.return_value = _count_result(7)
    assert await count_active_skus(db, TENANT_ID) == 7


@pytest.mark.asyncio
async def test_count_billable_users() -> None:
    db = AsyncMock()
    db.execute.return_value = _count_result(3)
    assert await count_billable_users(db, TENANT_ID) == 3


@pytest.mark.asyncio
async def test_count_active_warehouses() -> None:
    db = AsyncMock()
    db.execute.return_value = _count_result(2)
    assert await count_active_warehouses(db, TENANT_ID) == 2


@pytest.mark.asyncio
async def test_get_plan_usage_with_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    entitlements = {
        "plan_tier": "STARTER",
        "feature_flags": {},
        "sku_cap": 500,
        "max_warehouses": 3,
        "max_users": 5,
        "addons": [],
    }
    monkeypatch.setattr("shared.plans.usage.get_tenant_entitlements", AsyncMock(return_value=entitlements))
    monkeypatch.setattr("shared.plans.usage.count_active_skus", AsyncMock(return_value=10))
    monkeypatch.setattr("shared.plans.usage.count_billable_users", AsyncMock(return_value=2))
    monkeypatch.setattr("shared.plans.usage.count_active_warehouses", AsyncMock(return_value=1))

    usage = await get_plan_usage(AsyncMock(), TENANT_ID)

    assert usage == {
        "plan_tier": "STARTER",
        "skus": {"used": 10, "limit": 500},
        "users": {"used": 2, "limit": 5},
        "warehouses": {"used": 1, "limit": 3},
    }


@pytest.mark.asyncio
async def test_get_plan_usage_unlimited_caps_are_null(monkeypatch: pytest.MonkeyPatch) -> None:
    entitlements = {
        "plan_tier": "ENTERPRISE",
        "feature_flags": {},
        "sku_cap": None,
        "max_warehouses": None,
        "max_users": None,
        "addons": [],
    }
    monkeypatch.setattr("shared.plans.usage.get_tenant_entitlements", AsyncMock(return_value=entitlements))
    monkeypatch.setattr("shared.plans.usage.count_active_skus", AsyncMock(return_value=5000))
    monkeypatch.setattr("shared.plans.usage.count_billable_users", AsyncMock(return_value=40))
    monkeypatch.setattr("shared.plans.usage.count_active_warehouses", AsyncMock(return_value=12))

    usage = await get_plan_usage(AsyncMock(), TENANT_ID)

    assert usage["skus"]["limit"] is None
    assert usage["users"]["limit"] is None
    assert usage["warehouses"]["limit"] is None


@pytest.mark.asyncio
async def test_get_plan_usage_missing_tenant_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shared.plans.usage.get_tenant_entitlements", AsyncMock(return_value={}))
    usage = await get_plan_usage(AsyncMock(), TENANT_ID)
    assert usage == {}
