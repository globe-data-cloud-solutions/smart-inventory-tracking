"""Unit tests for plan_middleware — feature flag and resource limit checks."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from shared.permissions.plan_middleware import (
    ACTION_FLAG_MAP,
    _required_flag,
    check_plan,
    check_plan_create_user,
    check_plan_create_warehouse,
    requires_flag,
)
from shared.permissions.middleware import PermissionResult, require_permission
from shared.permissions.registry import PERMISSIONS, Permission
from shared.plans.catalog import KNOWN_FEATURE_FLAGS

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


def _addon_result(codes: list[str] | None = None) -> MagicMock:
    """get_tenant_entitlements()'s second query: ACTIVE tenant_addons codes."""
    result = MagicMock()
    result.fetchall.return_value = [MagicMock(addon_code=c) for c in (codes or [])]
    return result


def _db_plan_only(plan_result: MagicMock, addon_codes: list[str] | None = None) -> AsyncMock:
    """DB mock for two execute calls: plan fetch + the entitlements addon query."""
    db = AsyncMock()
    db.execute.side_effect = [plan_result, _addon_result(addon_codes)]
    return db


def _db_plan_then_count(plan_result: MagicMock, count: int, addon_codes: list[str] | None = None) -> AsyncMock:
    """DB mock for four execute calls: plan fetch, addon query, tenant FOR UPDATE lock, COUNT(*)."""
    lock_result = MagicMock()
    count_result = MagicMock()
    count_result.scalar.return_value = count
    db = AsyncMock()
    db.execute.side_effect = [plan_result, _addon_result(addon_codes), lock_result, count_result]
    return db


# ── SA bypass / TA gated ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sa_bypasses_feature_flag_check() -> None:
    db = AsyncMock()
    await check_plan(_user(role="SA"), "transfer:sister", db)
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_ta_gated_by_feature_flag() -> None:
    """TA is no longer exempt — a false flag must still raise 402 for TA."""
    plan = _plan_result(
        plan_tier="GROWTH",
        feature_flags={"TRANSFERS_SISTER": False},
    )
    db = _db_plan_only(plan)

    with pytest.raises(HTTPException) as exc_info:
        await check_plan(_user(role="TA"), "transfer:sister", db)

    assert exc_info.value.status_code == 402
    assert exc_info.value.detail["code"] == "FEATURE_NOT_IN_PLAN"


@pytest.mark.asyncio
async def test_sa_bypasses_warehouse_limit() -> None:
    db = AsyncMock()
    await check_plan_create_warehouse(_user(role="SA"), db)
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_ta_not_bypassed_unlimited_plan_passes() -> None:
    # TA is NOT bypassed by check_plan_create_user (only SA is exempt).
    # With max_users=None (unlimited plan) the function fetches the plan
    # (now two calls: tenant row + get_tenant_entitlements()'s addon query)
    # and returns early — no lock or count query issued.
    plan = _plan_result(plan_tier="ENTERPRISE", max_users=None)
    db = _db_plan_only(plan)
    await check_plan_create_user(_user(role="TA"), db)
    assert db.execute.call_count == 2


# ── tenant_id None → SA platform action bypass ────────────────────────────────

@pytest.mark.asyncio
async def test_no_tenant_id_bypasses_all_checks() -> None:
    db = AsyncMock()
    await check_plan(_user(role="NM", tenant_id=None), "transfer:sister", db)
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
        await check_plan(_user(), "transfer:sister", db)

    assert exc_info.value.status_code == 402
    detail = exc_info.value.detail
    assert detail["code"] == "FEATURE_NOT_IN_PLAN"
    assert detail["feature"] == "TRANSFERS_SISTER"
    assert detail["plan_tier"] == "GROWTH"
    assert detail["upgrade_to"] == "ENTERPRISE"


# ── Feature flag MISSING (not just False) → 402, deny-by-default (S10) ───────

@pytest.mark.asyncio
async def test_feature_flag_missing_key_raises_402() -> None:
    """A flag absent from feature_flags entirely (not even an explicit False)
    must deny exactly like False — feature_flags.get(flag, False) is
    deny-by-default, not "not yet enforced" (see plan_middleware.py comment
    fixed in S10)."""
    plan = _plan_result(plan_tier="GROWTH", feature_flags={})
    db = _db_plan_only(plan)

    with pytest.raises(HTTPException) as exc_info:
        await check_plan(_user(), "transfer:sister", db)

    assert exc_info.value.status_code == 402
    assert exc_info.value.detail["code"] == "FEATURE_NOT_IN_PLAN"


# ── Feature flag True → passes ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_feature_flag_true_passes() -> None:
    plan = _plan_result(
        plan_tier="ENTERPRISE",
        feature_flags={"TRANSFERS_SISTER": True},
    )
    db = _db_plan_only(plan)
    # Should not raise
    await check_plan(_user(), "transfer:sister", db)


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
    # max_warehouses=30 → total_allowed = 30 + 1 = 31 (1 free root slot).
    # count=31 exactly hits the cap (31 >= 31). count=30 would NOT trigger it.
    plan = _plan_result(plan_tier="GROWTH", max_warehouses=30)
    db = _db_plan_then_count(plan, count=31)

    with pytest.raises(HTTPException) as exc_info:
        await check_plan_create_warehouse(_user(), db)

    assert exc_info.value.status_code == 402
    detail = exc_info.value.detail
    assert detail["code"] == "PLAN_LIMIT_REACHED"
    assert detail["resource"] == "warehouses"
    assert detail["current"] == 31
    assert detail["limit"] == 30


# ── Warehouse limit NULL → unlimited, passes ─────────────────────────────────

@pytest.mark.asyncio
async def test_warehouse_limit_null_passes() -> None:
    plan = _plan_result(plan_tier="ENTERPRISE", max_warehouses=None)
    db = _db_plan_only(plan)
    await check_plan_create_warehouse(_user(), db)
    # Plan fetch + entitlements addon query; count query never issued
    assert db.execute.call_count == 2


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
    assert db.execute.call_count == 2


# ── TA is subject to warehouse limit (not bypassed) ──────────────────────────

@pytest.mark.asyncio
async def test_ta_warehouse_limit_enforced() -> None:
    """TA must respect the tenant's warehouse cap (only SA is exempt)."""
    # max_warehouses=3 → total_allowed = 3 + 1 = 4. count=4 hits the cap.
    plan = _plan_result(plan_tier="STARTER", max_warehouses=3)
    db = _db_plan_then_count(plan, count=4)

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


# ── _required_flag / requires_flag mapping ───────────────────────────────────

@pytest.mark.parametrize(
    "action_id,expected_flag",
    [
        ("tenant:upload_branding", "CUSTOM_BRANDING"),
        ("logistics:fleet_manage", "LOGISTICS"),
        ("ai:forecast_view", "AI_ANALYTICS"),
        ("audit:export_logs", "AUDIT_EXPORT"),
        ("transfer:create", None),
        ("product:create", None),
        ("report:lot_trace", None),
    ],
)
def test_required_flag_mapping(action_id: str, expected_flag: str | None) -> None:
    assert _required_flag(action_id) == expected_flag
    assert requires_flag(action_id) == (expected_flag is not None)


# ── Drift guard — ACTION_FLAG_MAP stays consistent with the registry ────────

def test_action_flag_map_values_are_known_feature_flags() -> None:
    for flag in ACTION_FLAG_MAP.values():
        assert flag in KNOWN_FEATURE_FLAGS


def test_action_flag_map_keys_match_a_registry_action() -> None:
    # "transfer:sister" is a pseudo-action passed by the explicit check_plan()
    # call in transfer.py's create_transfer handler — it has no registry
    # Permission/action id of its own (TRANSFER_CREATE covers that route).
    manual_keys = {"transfer:sister"}
    all_action_ids = [
        v.id for v in vars(PERMISSIONS).values() if isinstance(v, Permission)
    ]
    for key in ACTION_FLAG_MAP:
        if key in manual_keys:
            continue
        assert any(aid == key or aid.startswith(key) for aid in all_action_ids), (
            f"ACTION_FLAG_MAP key {key!r} matches no action id in the registry"
        )


# ── require_permission integration — plan gate runs after RBAC ──────────────

@require_permission(PERMISSIONS.TENANT_UPLOAD_BRANDING)
async def _branding_handler(user=None, db=None) -> str:
    return "handler ran"


@require_permission(PERMISSIONS.PRODUCT_CREATE)
async def _product_create_handler(user=None, db=None) -> str:
    return "handler ran"


# The read-only (contract stage) gate runs BEFORE the plan gate inside
# require_permission() and queries the DB itself — patch it to ACTIVE in
# these plan-gate-focused tests so it never consumes from the plan/addon
# db.execute side_effect queues below.
_ACTIVE_STAGE = {"stage": "ACTIVE", "contract_end": None, "read_only_since": None}


@pytest.mark.asyncio
async def test_require_permission_ta_gated_by_flag_false() -> None:
    plan = _plan_result(
        plan_tier="GROWTH", feature_flags={"CUSTOM_BRANDING": False}
    )
    db = _db_plan_only(plan)
    with patch(
        "shared.permissions.middleware.check_permission",
        AsyncMock(return_value=PermissionResult(allowed=True)),
    ), patch(
        "shared.billing.contract_stage.get_tenant_contract_stage",
        AsyncMock(return_value=_ACTIVE_STAGE),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await _branding_handler(user=_user(role="TA"), db=db)
    assert exc_info.value.status_code == 402
    assert exc_info.value.detail["code"] == "FEATURE_NOT_IN_PLAN"


@pytest.mark.asyncio
async def test_require_permission_ta_passes_when_flag_true() -> None:
    plan = _plan_result(
        plan_tier="ENTERPRISE", feature_flags={"CUSTOM_BRANDING": True}
    )
    db = _db_plan_only(plan)
    with patch(
        "shared.permissions.middleware.check_permission",
        AsyncMock(return_value=PermissionResult(allowed=True)),
    ), patch(
        "shared.billing.contract_stage.get_tenant_contract_stage",
        AsyncMock(return_value=_ACTIVE_STAGE),
    ):
        result = await _branding_handler(user=_user(role="TA"), db=db)
    assert result == "handler ran"


@pytest.mark.asyncio
async def test_require_permission_sa_bypasses_plan_gate() -> None:
    db = AsyncMock()
    with patch(
        "shared.permissions.middleware.check_permission",
        AsyncMock(return_value=PermissionResult(allowed=True)),
    ):
        result = await _branding_handler(user=_user(role="SA"), db=db)
    assert result == "handler ran"
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_require_permission_rbac_denied_is_403_not_402() -> None:
    db = AsyncMock()
    with patch(
        "shared.permissions.middleware.check_permission",
        AsyncMock(return_value=PermissionResult(allowed=False, reason="RBAC_DENIED")),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await _branding_handler(user=_user(role="TA"), db=db)
    assert exc_info.value.status_code == 403
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_require_permission_mapped_action_no_db_raises_500() -> None:
    # The read-only gate now runs before the plan gate and also needs a db
    # session for a non-exempt write action — with db=None it raises its own
    # CONTRACT_CHECK_NO_DB before PLAN_CHECK_NO_DB is ever reached.
    with patch(
        "shared.permissions.middleware.check_permission",
        AsyncMock(return_value=PermissionResult(allowed=True)),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await _branding_handler(user=_user(role="TA"), db=None)
    assert exc_info.value.status_code == 500
    assert exc_info.value.detail["code"] == "CONTRACT_CHECK_NO_DB"


@pytest.mark.asyncio
async def test_require_permission_unmapped_action_skips_entitlements() -> None:
    # product:create is a write action (not read_only_exempt), so the
    # read-only gate still issues ONE db.execute (contract stage lookup)
    # even though the plan gate itself skips entitlements for this action.
    db = AsyncMock()
    with patch(
        "shared.permissions.middleware.check_permission",
        AsyncMock(return_value=PermissionResult(allowed=True)),
    ), patch(
        "shared.billing.contract_stage.get_tenant_contract_stage",
        AsyncMock(return_value=_ACTIVE_STAGE),
    ) as mock_stage:
        result = await _product_create_handler(user=_user(role="TA"), db=db)
    assert result == "handler ran"
    mock_stage.assert_awaited_once()
    db.execute.assert_not_called()
