"""S9-1 — contract dates are independent of the billing period (CLAUDE.md §15
decision B).

The CONTRACT (tenants.contract_start/end) is the commercial agreement; the
SUBSCRIPTION period is the billing cycle. They are independent except that the
subscription's first period starts on the contract start (or today if none
given). mark_paid's GREATEST rule (contract_end never moves backwards) is
unchanged by this feature and not retested here — see
backend/shared/billing/tests/test_payments.py.

Same mocking pattern as test_security_fixes.py's TestTenantCustomSlug: a fake
db.execute routes platform_tier_config / package_prices reads to fixture rows
and records every (sql, params) pair so assertions can inspect exactly what
was written.
"""
from __future__ import annotations

import os
import sys
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL",      "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("DATABASE_READ_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("JWT_SECRET",        "test-secret")
os.environ.setdefault("JWT_SECRET_KEY",    "test-secret")
os.environ.setdefault("ENVIRONMENT",       "local")

_TENANT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _TENANT_ROOT not in sys.path:
    sys.path.insert(0, _TENANT_ROOT)

import pytest  # noqa: E402 - sys.path/env setup above must run first
from fastapi import HTTPException  # noqa: E402 - sys.path/env setup above must run first

pytestmark = pytest.mark.asyncio


def _user(role: str, tenant_id: str | None = None):
    from dependencies import UserContext
    return UserContext(user_id="u-1", role=role, tenant_id=tenant_id, warehouse_id=None)


def _catalog_row(tier: str = "GROWTH") -> MagicMock:
    row = MagicMock()
    row.tier = tier
    row.display_name = tier.capitalize()
    row.max_warehouses = 10
    row.max_users = 25
    row.sku_cap = 1500
    row.feature_flags = {"CORE_INVENTORY": True}
    row.is_public = True
    row.sort_order = 1
    return row


def _price_row(tier: str = "GROWTH") -> MagicMock:
    row = MagicMock()
    row.id = f"price-{tier.lower()}"
    row.tier = tier
    row.currency = "ETB"
    row.amount = Decimal("2000.00")
    return row


def _make_tracking_db(calls: list):
    """A fake AsyncSession whose execute() logs every (sql, params) pair and
    answers platform_tier_config / package_prices reads with fixture rows."""
    async def _execute(sql, params=None, **kw):
        calls.append((str(sql), dict(params) if params else {}))
        res = MagicMock()
        if "platform_tier_config" in str(sql):
            res.fetchone = MagicMock(return_value=_catalog_row())
        elif "package_prices" in str(sql):
            res.fetchone = MagicMock(return_value=_price_row())
        else:
            res.fetchone = MagicMock(return_value=None)   # no slug collision, no tenant row
            res.scalar   = MagicMock(return_value=None)
        return res

    db = AsyncMock()
    db.commit = AsyncMock()
    db.execute = AsyncMock(side_effect=_execute)
    return db


def _grant():
    from shared.permissions.store import RolePermissionGrant as PermissionGrant
    return PermissionGrant(role="SA", action_id="tenant:create", grant_type="FULL")


async def _create(body, calls):
    from routers.tenants import create_tenant
    caller = _user("SA")
    db = _make_tracking_db(calls)
    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_grant())):
        with patch("shared.permissions.audit.audit_log", new=AsyncMock()):
            resp = await create_tenant(body=body, user=caller, db=db)
    return resp, calls


def _contract_update_call(calls):
    """The explicit contract-override UPDATE this feature adds in create_tenant
    (params cs/ce/id) — distinct from start_subscription()'s own conditional
    UPDATE ... WHERE contract_start IS NULL (params start/end/tid)."""
    for sql, params in calls:
        if "UPDATE tenants SET" in sql and set(params) == {"cs", "ce", "id"}:
            return params
    return None


@pytest.mark.unit
class TestContractIndependentOfBillingPeriod:

    async def test_two_year_contract_with_annual_billing(self):
        """2-year contract + ANNUAL billing -> subscription period is 1 year,
        contract spans the full 2 years the caller asked for."""
        from schemas.tenant import TenantCreateRequest

        body = TenantCreateRequest(
            name="Two Year Co", organisation_type="PRODUCER",
            contract_start="2026-11-01", contract_end="2028-10-31",
            billing_period="ANNUAL",
        )
        calls: list = []
        resp, calls = await _create(body, calls)

        assert resp.data.contract_start == "2026-11-01"
        assert resp.data.contract_end == "2028-10-31"

        contract_params = _contract_update_call(calls)
        assert contract_params == {
            "cs": date(2026, 11, 1), "ce": date(2028, 10, 31), "id": str(resp.data.id),
        }

    async def test_contract_end_defaults_to_subscription_period_end(self):
        """Only contract_start given -> contract_end defaults to the
        subscription's own period end (MONTHLY: +1 month)."""
        from schemas.tenant import TenantCreateRequest

        body = TenantCreateRequest(
            name="Start Only Co", organisation_type="PRODUCER",
            contract_start="2026-11-01", billing_period="MONTHLY",
        )
        calls: list = []
        resp, calls = await _create(body, calls)

        assert resp.data.contract_start == "2026-11-01"
        assert resp.data.contract_end == "2026-12-01"

        contract_params = _contract_update_call(calls)
        assert contract_params["cs"] == date(2026, 11, 1)
        assert contract_params["ce"] == date(2026, 12, 1)

    async def test_invalid_contract_dates_rejected(self):
        """contract_end <= contract_start -> 422 INVALID_CONTRACT_DATES, before
        any DB call is made."""
        from routers.tenants import create_tenant
        from schemas.tenant import TenantCreateRequest

        body = TenantCreateRequest(
            name="Bad Dates Co", organisation_type="PRODUCER",
            contract_start="2026-11-01", contract_end="2026-11-01",
        )
        caller = _user("SA")
        db = AsyncMock()

        with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_grant())):
            with patch("shared.permissions.audit.audit_log", new=AsyncMock()):
                with pytest.raises(HTTPException) as exc_info:
                    await create_tenant(body=body, user=caller, db=db)

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "INVALID_CONTRACT_DATES"
        db.execute.assert_not_called()

    async def test_contract_end_only_in_past_rejected(self):
        """contract_end given WITHOUT contract_start implicitly starts the
        contract today — a past/today contract_end must be rejected with 422
        INVALID_CONTRACT_DATES before any DB call (S10-1b)."""
        from routers.tenants import create_tenant
        from schemas.tenant import TenantCreateRequest

        body = TenantCreateRequest(
            name="Past End Co", organisation_type="PRODUCER",
            contract_end="2020-01-01",
        )
        caller = _user("SA")
        db = AsyncMock()

        with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_grant())):
            with patch("shared.permissions.audit.audit_log", new=AsyncMock()):
                with pytest.raises(HTTPException) as exc_info:
                    await create_tenant(body=body, user=caller, db=db)

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "INVALID_CONTRACT_DATES"
        db.execute.assert_not_called()

    async def test_contract_end_only_in_future_accepted(self):
        """contract_end given WITHOUT contract_start, in the future -> accepted,
        effective_start defaults to today (S10-1b)."""
        from schemas.tenant import TenantCreateRequest
        from datetime import timedelta

        future_end = (date.today() + timedelta(days=365)).isoformat()
        body = TenantCreateRequest(
            name="Future End Co", organisation_type="PRODUCER",
            contract_end=future_end,
        )
        calls: list = []
        resp, calls = await _create(body, calls)

        assert resp.data.contract_start == str(date.today())
        assert resp.data.contract_end == future_end

    async def test_invalid_billing_period_rejected(self):
        """billing_period outside MONTHLY/ANNUAL -> 422 INVALID_BILLING_PERIOD,
        before any DB call is made."""
        from routers.tenants import create_tenant
        from schemas.tenant import TenantCreateRequest

        body = TenantCreateRequest(name="Bad Period Co", organisation_type="PRODUCER", billing_period="WEEKLY")
        caller = _user("SA")
        db = AsyncMock()

        with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_grant())):
            with patch("shared.permissions.audit.audit_log", new=AsyncMock()):
                with pytest.raises(HTTPException) as exc_info:
                    await create_tenant(body=body, user=caller, db=db)

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "INVALID_BILLING_PERIOD"
        db.execute.assert_not_called()

    async def test_create_without_contract_dates_unchanged(self):
        """Omitting contract dates behaves exactly as before this feature:
        start_subscription() derives both subscription and contract dates
        (today .. period_end), and no explicit contract UPDATE is issued."""
        from schemas.tenant import TenantCreateRequest

        body = TenantCreateRequest(name="Default Co", organisation_type="PRODUCER")
        calls: list = []
        resp, calls = await _create(body, calls)

        assert _contract_update_call(calls) is None
        assert resp.data.contract_start == str(date.today())


@pytest.mark.unit
class TestPatchContractLeavesSubscriptionUnchanged:

    async def test_patch_contract_touches_only_tenants_table(self):
        """PATCH /{tenant_id}/contract must never write to subscriptions —
        contract and billing period are independent (CLAUDE.md §15 decision B)."""
        from routers.tenants import update_tenant_contract, ContractUpdateRequest

        tenant_row = MagicMock()
        tenant_row.id = "t-1"
        tenant_row.name = "Existing Co"
        tenant_row.status = "ACTIVE"
        tenant_row.contract_start = date(2026, 1, 1)
        tenant_row.contract_end = date(2027, 1, 1)

        calls: list = []

        async def _execute(sql, params=None, **kw):
            calls.append(str(sql))
            res = MagicMock()
            res.fetchone = MagicMock(return_value=tenant_row)
            return res

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=_execute)
        caller = _user("SA")

        body = ContractUpdateRequest(contract_start="2026-01-01", contract_end="2028-01-01", note="extend")
        with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_grant())):
            with patch("shared.permissions.audit.audit_log", new=AsyncMock()):
                with patch("routers.tenants._log_tenant_activity", new=AsyncMock()):
                    await update_tenant_contract(tenant_id="t-1", body=body, user=caller, db=db)

        assert not any("subscriptions" in c.lower() for c in calls)
        assert any("UPDATE tenants SET" in c and "contract_start" in c for c in calls)
