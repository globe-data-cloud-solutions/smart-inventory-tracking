"""Unit tests for the S2 package-catalog work.

  - shared.plans.catalog: get_package / apply_package_to_tenant (single
    source of plan limits and feature flags — migration 070).
  - routers.tenants._build_profile_update_set_clause: the A1 fix (org-type
    change sets approval_thresholds only, never feature_flags) — owed test.
  - routers.tenants.update_platform_tier_config: platform_config_log is
    written only for fields that actually changed.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("DATABASE_URL",      "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("DATABASE_READ_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("JWT_SECRET",        "test-secret")
os.environ.setdefault("JWT_SECRET_KEY",    "test-secret")
os.environ.setdefault("ENVIRONMENT",       "local")

_TENANT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _TENANT_ROOT not in sys.path:
    sys.path.insert(0, _TENANT_ROOT)

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

TENANT_ID = "aabbccdd-0000-0000-0000-000000000001"


def _user(role: str = "SA", tenant_id: str | None = None):
    from dependencies import UserContext
    return UserContext(user_id="u1", role=role, tenant_id=tenant_id, warehouse_id=None)


def _package_row(
    tier: str = "STARTER",
    max_warehouses: int | None = 3,
    max_users: int | None = 5,
    sku_cap: int | None = 500,
) -> MagicMock:
    row = MagicMock()
    row.tier = tier
    row.display_name = tier.capitalize()
    row.max_warehouses = max_warehouses
    row.max_users = max_users
    row.sku_cap = sku_cap
    row.feature_flags = {
        "CORE_INVENTORY": True, "TRANSFERS_PULL_PUSH": True, "LOT_TRACEABILITY": True,
        "TRANSFERS_SISTER": False, "LOGISTICS": False, "AUDIT_EXPORT": False,
        "CUSTOM_BRANDING": False, "AI_ANALYTICS": False, "API_ACCESS": False,
    }
    row.is_public = True
    row.sort_order = 1
    return row


# ── shared.plans.catalog ──────────────────────────────────────────────────────

@pytest.mark.unit
class TestPlanCatalog:

    @pytest.mark.asyncio
    async def test_apply_package_to_tenant_issues_one_update_with_full_package(self):
        from shared.plans.catalog import apply_package_to_tenant

        select_res = MagicMock()
        select_res.fetchone = MagicMock(return_value=_package_row("STARTER"))
        update_res = MagicMock()

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[select_res, update_res])

        effective = await apply_package_to_tenant(db, TENANT_ID, "STARTER")

        assert db.execute.call_count == 2
        update_call = db.execute.call_args_list[1]
        params = update_call.args[1]
        assert params["tier"] == "STARTER"
        assert params["max_wh"] == 3
        assert params["max_u"] == 5
        assert params["sku_cap"] == 500
        written_flags = json.loads(params["flags"])
        assert len(written_flags) == 9
        assert written_flags["TRANSFERS_SISTER"] is False

        assert effective == {
            "plan_tier": "STARTER",
            "max_warehouses": 3,
            "max_users": 5,
            "sku_cap": 500,
            "feature_flags": written_flags,
        }

    @pytest.mark.asyncio
    async def test_apply_package_to_tenant_explicit_max_users_override_wins(self):
        from shared.plans.catalog import apply_package_to_tenant

        select_res = MagicMock()
        select_res.fetchone = MagicMock(return_value=_package_row("GROWTH", max_users=25))
        update_res = MagicMock()
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[select_res, update_res])

        effective = await apply_package_to_tenant(db, TENANT_ID, "GROWTH", max_users=40)

        assert effective["max_users"] == 40
        params = db.execute.call_args_list[1].args[1]
        assert params["max_u"] == 40

    @pytest.mark.asyncio
    async def test_apply_package_to_tenant_sku_cap_none_override_means_unlimited(self):
        from shared.plans.catalog import apply_package_to_tenant

        select_res = MagicMock()
        select_res.fetchone = MagicMock(return_value=_package_row("STARTER", sku_cap=500))
        update_res = MagicMock()
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[select_res, update_res])

        effective = await apply_package_to_tenant(db, TENANT_ID, "STARTER", sku_cap=None)

        assert effective["sku_cap"] is None
        params = db.execute.call_args_list[1].args[1]
        assert params["sku_cap"] is None

    @pytest.mark.asyncio
    async def test_get_package_unknown_tier_raises_value_error(self):
        from shared.plans.catalog import get_package

        select_res = MagicMock()
        select_res.fetchone = MagicMock(return_value=None)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=select_res)

        with pytest.raises(ValueError, match="Unknown plan tier: BOGUS"):
            await get_package(db, "BOGUS")


# ── A1 owed test: org-type change never touches feature_flags ───────────────

@pytest.mark.unit
class TestProfileOrgTypeFlags:

    def test_org_type_change_sets_thresholds_not_flags(self):
        from routers.tenants import _build_profile_update_set_clause
        from routers.tenants import TenantProfileUpdateRequest

        changes = {"organisation_type": ("PRODUCER", "RETAILER")}
        body = TenantProfileUpdateRequest(organisation_type="RETAILER")

        set_parts, params = _build_profile_update_set_clause(changes, body)
        joined = " ".join(set_parts)

        assert "approval_thresholds" in joined
        assert "feature_flags" not in joined
        assert params["org_type"] == "RETAILER"

    def test_name_change_only_touches_name(self):
        from routers.tenants import _build_profile_update_set_clause
        from routers.tenants import TenantProfileUpdateRequest

        changes = {"name": ("Old Co", "New Co")}
        body = TenantProfileUpdateRequest(name="New Co")

        set_parts, params = _build_profile_update_set_clause(changes, body)
        joined = " ".join(set_parts)

        assert "name = :name" in joined
        assert "organisation_type" not in joined
        assert "feature_flags" not in joined
        assert params["name"] == "New Co"


# ── platform_config_log: only changed fields are logged ─────────────────────

@pytest.mark.unit
class TestTierConfigLog:

    @pytest.mark.asyncio
    async def test_patch_tier_config_logs_only_the_changed_field(self):
        from routers.tenants import update_platform_tier_config, TierConfigUpdateRequest, TierConfigEntry
        from shared.permissions.store import RolePermissionGrant as PermissionGrant

        caller = _user("SA")
        body = TierConfigUpdateRequest(tiers=[TierConfigEntry(tier="STARTER", max_warehouses=3, max_users=6)])

        old_row = MagicMock()
        old_row.max_warehouses = 3   # unchanged
        old_row.max_users = 5        # changes to 6

        select_old = MagicMock()
        select_old.fetchone = MagicMock(return_value=old_row)
        upsert_res = MagicMock()
        log_res = MagicMock()
        final_select = MagicMock()
        final_select.fetchall = MagicMock(return_value=[])

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[select_old, upsert_res, log_res, final_select])

        grant = PermissionGrant(role="SA", action_id="platform:tier_config_edit", grant_type="FULL")
        with patch("shared.permissions.middleware.get_role_permission",
                   new=AsyncMock(return_value=grant)):
            with patch("shared.permissions.audit.audit_log", new=AsyncMock()):
                await update_platform_tier_config(body=body, user=caller, db=db)

        assert db.execute.call_count == 4   # select old, upsert, ONE log insert, final select
        log_call_sql = str(db.execute.call_args_list[2].args[0])
        log_call_params = db.execute.call_args_list[2].args[1]
        assert "platform_config_log" in log_call_sql
        assert log_call_params["field"] == "max_users"
        assert log_call_params["old"] == "5"
        assert log_call_params["new"] == "6"

    @pytest.mark.asyncio
    async def test_patch_tier_config_unchanged_fields_write_no_log(self):
        from routers.tenants import update_platform_tier_config, TierConfigUpdateRequest, TierConfigEntry
        from shared.permissions.store import RolePermissionGrant as PermissionGrant

        caller = _user("SA")
        body = TierConfigUpdateRequest(tiers=[TierConfigEntry(tier="STARTER", max_warehouses=3, max_users=5)])

        old_row = MagicMock()
        old_row.max_warehouses = 3
        old_row.max_users = 5

        select_old = MagicMock()
        select_old.fetchone = MagicMock(return_value=old_row)
        upsert_res = MagicMock()
        final_select = MagicMock()
        final_select.fetchall = MagicMock(return_value=[])

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[select_old, upsert_res, final_select])

        grant = PermissionGrant(role="SA", action_id="platform:tier_config_edit", grant_type="FULL")
        with patch("shared.permissions.middleware.get_role_permission",
                   new=AsyncMock(return_value=grant)):
            with patch("shared.permissions.audit.audit_log", new=AsyncMock()):
                await update_platform_tier_config(body=body, user=caller, db=db)

        assert db.execute.call_count == 3   # select old, upsert, final select — no log insert
