"""Regression tests for RB-1 sweep HOLEs 1-3 (docs/reviews/2026-10-19-rb1-sweep.md):
tenants.py's get_tenant / get_approval_rules / put_approval_rules never checked
that the path tenant_id belonged to the caller. Fixed via
_resolve_and_authorize_tenant_id (fix/rb1-holes) — these tests prove the fix
actually bites (fail against pre-fix behaviour, pass after) and that SA access
is preserved.
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

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

pytestmark = pytest.mark.asyncio

TENANT_A = "aaaaaaaa-0000-0000-0000-000000000001"
TENANT_B = "bbbbbbbb-0000-0000-0000-000000000002"

# These tests exercise the route bodies' own tenant-ownership check, not RBAC —
# same convention as test_tenant_suspend_deactivate_revocation.py.
_GRANT_ALL = patch(
    "shared.permissions.middleware.check_permission",
    new=AsyncMock(return_value=MagicMock(allowed=True, condition=None)),
)


def _user(role: str, tenant_id: str | None) -> MagicMock:
    u = MagicMock()
    u.role, u.tenant_id = role, tenant_id
    return u


def _db_for_tenant_b() -> AsyncMock:
    """A tenant row that exists — belongs to TENANT_B."""
    db = AsyncMock()
    row = MagicMock()
    row.id, row.name, row.slug = TENANT_B, "Tenant B Inc", "tenant-b"
    row.organisation_type = "PRODUCER"
    row.onboarding_complete = True
    row.default_locale = "en"
    row.is_active = True
    row.status = "ACTIVE"
    row.logo_url = row.banner_url = None
    row.plan_tier = "STARTER"
    row.max_warehouses = row.max_users = 5
    row.contract_start = row.contract_end = None
    row.approval_thresholds = {"simple_mode": True, "rules": []}
    result = MagicMock(fetchone=MagicMock(return_value=row))
    db.execute = AsyncMock(return_value=result)
    return db


class TestGetTenant:
    async def test_ta_from_tenant_a_cannot_read_tenant_b(self) -> None:
        from routers.tenants import get_tenant

        with _GRANT_ALL, pytest.raises(HTTPException) as exc:
            await get_tenant(tenant_id=TENANT_B, user=_user("TA", TENANT_A), db=_db_for_tenant_b())
        assert exc.value.status_code == 403
        assert exc.value.detail["code"] == "TENANT_ACCESS_DENIED"

    async def test_sa_can_read_any_tenant(self) -> None:
        from routers.tenants import get_tenant

        with _GRANT_ALL:
            resp = await get_tenant(tenant_id=TENANT_B, user=_user("SA", None), db=_db_for_tenant_b())
        assert str(resp.data.id) == TENANT_B

    async def test_ta_from_tenant_b_can_read_own_tenant(self) -> None:
        from routers.tenants import get_tenant

        with _GRANT_ALL:
            resp = await get_tenant(tenant_id=TENANT_B, user=_user("TA", TENANT_B), db=_db_for_tenant_b())
        assert str(resp.data.id) == TENANT_B


class TestGetApprovalRules:
    async def test_ta_from_tenant_a_cannot_read_tenant_b_rules(self) -> None:
        from routers.tenants import get_approval_rules

        with _GRANT_ALL, pytest.raises(HTTPException) as exc:
            await get_approval_rules(tenant_id=TENANT_B, user=_user("TA", TENANT_A), db=_db_for_tenant_b())
        assert exc.value.status_code == 403
        assert exc.value.detail["code"] == "TENANT_ACCESS_DENIED"

    async def test_sa_can_read_any_tenants_rules(self) -> None:
        from routers.tenants import get_approval_rules

        with _GRANT_ALL:
            resp = await get_approval_rules(tenant_id=TENANT_B, user=_user("SA", None), db=_db_for_tenant_b())
        assert resp.data == []


class TestPutApprovalRules:
    async def test_ta_from_tenant_a_cannot_write_tenant_b_rules(self) -> None:
        from routers.tenants import put_approval_rules, ApprovalRulesBody

        body = ApprovalRulesBody(simple_mode=True, rules=[])
        with _GRANT_ALL, pytest.raises(HTTPException) as exc:
            await put_approval_rules(
                tenant_id=TENANT_B, body=body, user=_user("TA", TENANT_A), db=_db_for_tenant_b()
            )
        assert exc.value.status_code == 403
        assert exc.value.detail["code"] == "TENANT_ACCESS_DENIED"

    async def test_sa_can_write_any_tenants_rules(self) -> None:
        from routers.tenants import put_approval_rules, ApprovalRulesBody

        body = ApprovalRulesBody(simple_mode=True, rules=[])
        db = _db_for_tenant_b()
        with _GRANT_ALL:
            resp = await put_approval_rules(tenant_id=TENANT_B, body=body, user=_user("SA", None), db=db)
        assert resp.data == []

    async def test_ta_from_tenant_b_can_write_own_rules(self) -> None:
        from routers.tenants import put_approval_rules, ApprovalRulesBody

        body = ApprovalRulesBody(simple_mode=True, rules=[])
        db = _db_for_tenant_b()
        with _GRANT_ALL:
            resp = await put_approval_rules(tenant_id=TENANT_B, body=body, user=_user("TA", TENANT_B), db=db)
        assert resp.data == []


class TestSlugAccess:
    """HOLEs 1-3 are reachable via slug as well as UUID — the fix must cover both."""

    async def test_ta_from_tenant_a_cannot_read_tenant_b_by_slug(self) -> None:
        from routers.tenants import get_tenant

        db = AsyncMock()
        row = MagicMock()
        row.id, row.name, row.slug = TENANT_B, "Tenant B Inc", "tenant-b"
        row.organisation_type, row.onboarding_complete, row.default_locale = "PRODUCER", True, "en"
        row.is_active, row.status = True, "ACTIVE"
        row.logo_url = row.banner_url = None
        row.plan_tier, row.max_warehouses, row.max_users = "STARTER", 5, 5
        row.contract_start = row.contract_end = None
        # First call resolves the slug -> id (used by _resolve_and_authorize_tenant_id),
        # second would fetch the tenant row — never reached once denied.
        id_result = MagicMock(fetchone=MagicMock(return_value=MagicMock(id=TENANT_B)))
        db.execute = AsyncMock(return_value=id_result)

        with _GRANT_ALL, pytest.raises(HTTPException) as exc:
            await get_tenant(tenant_id="tenant-b", user=_user("TA", TENANT_A), db=db)
        assert exc.value.status_code == 403
        assert exc.value.detail["code"] == "TENANT_ACCESS_DENIED"
