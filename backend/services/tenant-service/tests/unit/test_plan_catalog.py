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

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("DATABASE_READ_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("ENVIRONMENT", "local")

_TENANT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _TENANT_ROOT not in sys.path:
    sys.path.insert(0, _TENANT_ROOT)

import json  # noqa: E402 - sys.path/env setup above must run first
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402 - sys.path/env setup above must run first

import pytest  # noqa: E402 - sys.path/env setup above must run first

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
        "CORE_INVENTORY": True,
        "TRANSFERS_PULL_PUSH": True,
        "LOT_TRACEABILITY": True,
        "TRANSFERS_SISTER": False,
        "LOGISTICS": False,
        "AUDIT_EXPORT": False,
        "CUSTOM_BRANDING": False,
        "AI_ANALYTICS": False,
        "API_ACCESS": False,
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
        from routers.tenants import (
            update_platform_tier_config,
            TierConfigUpdateRequest,
            TierConfigEntry,
        )
        from shared.permissions.store import RolePermissionGrant as PermissionGrant

        caller = _user("SA")
        body = TierConfigUpdateRequest(
            tiers=[TierConfigEntry(tier="STARTER", max_warehouses=3, max_users=6)]
        )

        old_row = MagicMock()
        old_row.max_warehouses = 3  # unchanged
        old_row.max_users = 5  # changes to 6

        public_check = MagicMock()
        public_check.fetchall = MagicMock(return_value=[MagicMock(tier="STARTER", is_public=True)])
        select_old = MagicMock()
        select_old.fetchone = MagicMock(return_value=old_row)
        update_res = MagicMock()
        log_res = MagicMock()
        final_select = MagicMock()
        final_select.fetchall = MagicMock(return_value=[])

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[public_check, select_old, update_res, log_res, final_select]
        )

        grant = PermissionGrant(role="SA", action_id="platform:tier_config_edit", grant_type="FULL")
        with patch(
            "shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=grant)
        ):
            with patch("shared.permissions.audit.audit_log", new=AsyncMock()):
                await update_platform_tier_config(body=body, user=caller, db=db)

        assert (
            db.execute.call_count == 5
        )  # public check, select old, update, ONE log insert, final select
        log_call_sql = str(db.execute.call_args_list[3].args[0])
        log_call_params = db.execute.call_args_list[3].args[1]
        assert "platform_config_log" in log_call_sql
        assert log_call_params["field"] == "max_users"
        assert log_call_params["old"] == "5"
        assert log_call_params["new"] == "6"
        # No `reason` sent (legacy modal body) -> defaults, and the legacy call still succeeds.
        assert log_call_params["reason"] == "SA tier-config edit"

    @pytest.mark.asyncio
    async def test_patch_tier_config_unchanged_fields_write_no_log(self):
        from routers.tenants import (
            update_platform_tier_config,
            TierConfigUpdateRequest,
            TierConfigEntry,
        )
        from shared.permissions.store import RolePermissionGrant as PermissionGrant

        caller = _user("SA")
        body = TierConfigUpdateRequest(
            tiers=[TierConfigEntry(tier="STARTER", max_warehouses=3, max_users=5)]
        )

        old_row = MagicMock()
        old_row.max_warehouses = 3
        old_row.max_users = 5

        public_check = MagicMock()
        public_check.fetchall = MagicMock(return_value=[MagicMock(tier="STARTER", is_public=True)])
        select_old = MagicMock()
        select_old.fetchone = MagicMock(return_value=old_row)
        update_res = MagicMock()
        final_select = MagicMock()
        final_select.fetchall = MagicMock(return_value=[])

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[public_check, select_old, update_res, final_select])

        grant = PermissionGrant(role="SA", action_id="platform:tier_config_edit", grant_type="FULL")
        with patch(
            "shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=grant)
        ):
            with patch("shared.permissions.audit.audit_log", new=AsyncMock()):
                await update_platform_tier_config(body=body, user=caller, db=db)

        assert (
            db.execute.call_count == 4
        )  # public check, select old, update, final select — no log insert

    @pytest.mark.asyncio
    async def test_patch_tier_config_partial_update_leaves_other_fields_untouched(self):
        """Sending only display_name must not touch max_warehouses/max_users/sku_cap/etc —
        the UPDATE's SET clause contains display_name only (plus updated_at/updated_by_id)."""
        from routers.tenants import (
            update_platform_tier_config,
            TierConfigUpdateRequest,
            TierConfigEntry,
        )
        from shared.permissions.store import RolePermissionGrant as PermissionGrant

        caller = _user("SA")
        body = TierConfigUpdateRequest(
            tiers=[TierConfigEntry(tier="GROWTH", display_name="Growth Plan")]
        )

        old_row = MagicMock(
            max_warehouses=10,
            max_users=25,
            display_name="Growth",
            sku_cap=1500,
            feature_flags={},
            is_public=True,
            sort_order=2,
        )
        public_check = MagicMock()
        public_check.fetchall = MagicMock(return_value=[MagicMock(tier="GROWTH", is_public=True)])
        select_old = MagicMock()
        select_old.fetchone = MagicMock(return_value=old_row)
        update_res = MagicMock()
        log_res = MagicMock()
        final_select = MagicMock()
        final_select.fetchall = MagicMock(return_value=[])

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[public_check, select_old, update_res, log_res, final_select]
        )

        grant = PermissionGrant(role="SA", action_id="platform:tier_config_edit", grant_type="FULL")
        with patch(
            "shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=grant)
        ):
            with patch("shared.permissions.audit.audit_log", new=AsyncMock()):
                await update_platform_tier_config(body=body, user=caller, db=db)

        update_call_sql = str(db.execute.call_args_list[2].args[0])
        assert "display_name" in update_call_sql
        for untouched in (
            "max_warehouses",
            "max_users",
            "sku_cap",
            "is_public",
            "sort_order",
            "feature_flags",
        ):
            assert untouched not in update_call_sql
        log_call_params = db.execute.call_args_list[3].args[1]
        assert log_call_params["field"] == "display_name"

    @pytest.mark.asyncio
    async def test_patch_tier_config_unknown_feature_flag_rejected(self):
        from fastapi import HTTPException
        from routers.tenants import (
            update_platform_tier_config,
            TierConfigUpdateRequest,
            TierConfigEntry,
        )
        from shared.permissions.store import RolePermissionGrant as PermissionGrant

        caller = _user("SA")
        body = TierConfigUpdateRequest(
            tiers=[TierConfigEntry(tier="STARTER", feature_flags={"BOGUS_FLAG": True})]
        )
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=AssertionError("must not query the DB before validation")
        )

        grant = PermissionGrant(role="SA", action_id="platform:tier_config_edit", grant_type="FULL")
        with patch(
            "shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=grant)
        ):
            with patch("shared.permissions.audit.audit_log", new=AsyncMock()):
                with pytest.raises(HTTPException) as exc_info:
                    await update_platform_tier_config(body=body, user=caller, db=db)

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "UNKNOWN_FEATURE_FLAG"

    @pytest.mark.asyncio
    async def test_patch_tier_config_last_public_package_rejected(self):
        from fastapi import HTTPException
        from routers.tenants import (
            update_platform_tier_config,
            TierConfigUpdateRequest,
            TierConfigEntry,
        )
        from shared.permissions.store import RolePermissionGrant as PermissionGrant

        caller = _user("SA")
        body = TierConfigUpdateRequest(tiers=[TierConfigEntry(tier="STARTER", is_public=False)])

        # Only STARTER is currently public; GROWTH/ENTERPRISE are already not public.
        public_check = MagicMock()
        public_check.fetchall = MagicMock(
            return_value=[
                MagicMock(tier="STARTER", is_public=True),
                MagicMock(tier="GROWTH", is_public=False),
                MagicMock(tier="ENTERPRISE", is_public=False),
            ]
        )
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[public_check])

        grant = PermissionGrant(role="SA", action_id="platform:tier_config_edit", grant_type="FULL")
        with patch(
            "shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=grant)
        ):
            with patch("shared.permissions.audit.audit_log", new=AsyncMock()):
                with pytest.raises(HTTPException) as exc_info:
                    await update_platform_tier_config(body=body, user=caller, db=db)

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "NO_PUBLIC_PACKAGE"


@pytest.mark.unit
class TestPlatformPackagePrices:
    """POST /platform/packages/{tier}/prices — reason required, effective_from guard,
    and the config-log entry on success."""

    @pytest.mark.asyncio
    async def test_create_price_reason_required(self):
        from fastapi import HTTPException
        from routers.tenants import create_platform_package_price, PriceCreateRequest
        from shared.permissions.store import RolePermissionGrant as PermissionGrant

        caller = _user("SA")
        body = PriceCreateRequest(billing_period="MONTHLY", amount="150.00", reason="   ")
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=AssertionError("must not query the DB before validation")
        )

        grant = PermissionGrant(role="SA", action_id="platform:tier_config_edit", grant_type="FULL")
        with patch(
            "shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=grant)
        ):
            with patch("shared.permissions.audit.audit_log", new=AsyncMock()):
                with pytest.raises(HTTPException) as exc_info:
                    await create_platform_package_price(
                        tier="STARTER", body=body, user=caller, db=db
                    )

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "REASON_REQUIRED"

    @pytest.mark.asyncio
    async def test_create_price_effective_from_in_past_rejected(self):
        from datetime import datetime, timedelta, timezone
        from fastapi import HTTPException
        from routers.tenants import create_platform_package_price, PriceCreateRequest
        from shared.permissions.store import RolePermissionGrant as PermissionGrant

        caller = _user("SA")
        body = PriceCreateRequest(
            billing_period="MONTHLY",
            amount="150.00",
            reason="correction",
            effective_from=datetime.now(timezone.utc) - timedelta(days=1),
        )
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=AssertionError("must not query the DB before validation")
        )

        grant = PermissionGrant(role="SA", action_id="platform:tier_config_edit", grant_type="FULL")
        with patch(
            "shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=grant)
        ):
            with patch("shared.permissions.audit.audit_log", new=AsyncMock()):
                with pytest.raises(HTTPException) as exc_info:
                    await create_platform_package_price(
                        tier="STARTER", body=body, user=caller, db=db
                    )

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "EFFECTIVE_FROM_IN_PAST"

    @pytest.mark.asyncio
    async def test_create_price_success_writes_price_and_config_log(self):
        from routers.tenants import create_platform_package_price, PriceCreateRequest
        from shared.permissions.store import RolePermissionGrant as PermissionGrant

        caller = _user("SA")
        body = PriceCreateRequest(billing_period="MONTHLY", amount="120.00", reason="price update")

        old_price_row = MagicMock(id="price-old", amount="100.00")
        current_price_result = MagicMock()
        current_price_result.fetchone = MagicMock(return_value=old_price_row)
        insert_price_result = MagicMock()
        insert_price_result.scalar_one = MagicMock(return_value="price-new")
        log_result = MagicMock()

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[current_price_result, insert_price_result, log_result])

        grant = PermissionGrant(role="SA", action_id="platform:tier_config_edit", grant_type="FULL")
        with patch(
            "shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=grant)
        ):
            with patch("shared.permissions.audit.audit_log", new=AsyncMock()):
                result = await create_platform_package_price(
                    tier="STARTER", body=body, user=caller, db=db
                )

        assert result.data["id"] == "price-new"
        insert_sql = str(db.execute.call_args_list[1].args[0])
        assert "INSERT INTO package_prices" in insert_sql
        log_params = db.execute.call_args_list[2].args[1]
        assert log_params["key"] == "STARTER/MONTHLY"
        assert log_params["old"] == "100.00"
        assert log_params["reason"] == "price update"


@pytest.mark.unit
class TestRegistryBillingColumns:
    """GET /sa/registry — new signup_source/subscription/payment columns."""

    @pytest.mark.asyncio
    async def test_registry_row_includes_billing_columns(self):
        from routers.tenants import sa_tenant_registry
        from shared.permissions.store import RolePermissionGrant as PermissionGrant
        import datetime as _dt

        caller = _user("SA")
        row = MagicMock(
            id="00000000-0000-0000-0000-000000000001",
            slug="acme",
            organisation_type="RETAILER",
            status="ACTIVE",
            plan_tier="GROWTH",
            default_locale="en",
            contact_name=None,
            contact_email=None,
            contact_phone=None,
            contract_start=None,
            contract_end=None,
            notes=None,
            sku_cap=None,
            address_line1=None,
            address_line2=None,
            city=None,
            state_province=None,
            postal_code=None,
            country=None,
            industry=None,
            feature_flags={},
            created_at=_dt.datetime(2026, 10, 1, tzinfo=_dt.timezone.utc),
            signup_source="SELF_SIGNUP",
            subscription_status="ACTIVE",
            billing_period="ANNUAL",
            current_period_end=_dt.date(2027, 10, 1),
            last_payment_status="PAID",
            contacts=[],
            ta_name=None,
            ta_email=None,
            ta_user_id=None,
        )
        row.name = "Acme"  # "name" is a reserved MagicMock constructor kwarg — set separately
        select_result = MagicMock()
        select_result.fetchall = MagicMock(return_value=[row])

        db = AsyncMock()
        db.execute = AsyncMock(return_value=select_result)

        grant = PermissionGrant(role="SA", action_id="tenant:registry_view", grant_type="FULL")
        with patch(
            "shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=grant)
        ):
            with patch("shared.permissions.audit.audit_log", new=AsyncMock()):
                result = await sa_tenant_registry(user=caller, db=db)

        out = result.data[0]
        assert out.signup_source == "SELF_SIGNUP"
        assert out.subscription_status == "ACTIVE"
        assert out.billing_period == "ANNUAL"
        assert out.current_period_end == "2027-10-01"
        assert out.last_payment_status == "PAID"
