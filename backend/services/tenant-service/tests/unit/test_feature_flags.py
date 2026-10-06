"""PATCH /{tenant_id}/feature-flags — regression test for a missing `return`
after a successful update (the handler fell off the end on any real change,
returning None and failing FastAPI's response_model validation with a 500).
Surfaced by the SA tenant page's Feature overrides toggle (CLAUDE.md §15 S9).
"""
from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL",      "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("DATABASE_READ_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("JWT_SECRET",        "test-secret")
os.environ.setdefault("JWT_SECRET_KEY",    "test-secret")
os.environ.setdefault("ENVIRONMENT",       "local")

_TENANT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _TENANT_ROOT not in sys.path:
    sys.path.insert(0, _TENANT_ROOT)

import pytest

pytestmark = pytest.mark.asyncio


def _user(role: str = "SA"):
    from dependencies import UserContext
    return UserContext(user_id="u-1", role=role, tenant_id=None, warehouse_id=None)


def _grant():
    from shared.permissions.store import RolePermissionGrant as PermissionGrant
    return PermissionGrant(role="SA", action_id="tenant:manage", grant_type="FULL")


@pytest.mark.unit
class TestUpdateFeatureFlagsReturnsResponse:

    async def test_successful_change_returns_success_response_not_none(self):
        """A real change must return SuccessResponse — not fall off the end
        and return None (which fails response_model validation with a 500)."""
        from routers.tenants import update_feature_flags, FeatureFlagsUpdateRequest

        tenant_row = MagicMock()
        tenant_row.id = "t-1"
        tenant_row.name = "Probe Co"
        tenant_row.feature_flags = {"LOGISTICS": False}

        db = AsyncMock()

        async def _execute(sql, params=None, **kw):
            res = MagicMock()
            res.fetchone = MagicMock(return_value=tenant_row)
            return res

        db.execute = AsyncMock(side_effect=_execute)

        body = FeatureFlagsUpdateRequest(feature_flags={"LOGISTICS": True})
        with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_grant())):
            with patch("shared.permissions.audit.audit_log", new=AsyncMock()):
                with patch("routers.tenants._log_tenant_activity", new=AsyncMock()):
                    resp = await update_feature_flags(tenant_id="t-1", body=body, user=_user(), db=db)

        assert resp is not None
        assert resp.data["changes"] == 1
        assert resp.data["feature_flags"]["LOGISTICS"] is True

    async def test_no_change_still_returns_success_response(self):
        """Already-covered path (no changes) — same shape, no regression."""
        from routers.tenants import update_feature_flags, FeatureFlagsUpdateRequest

        tenant_row = MagicMock()
        tenant_row.id = "t-1"
        tenant_row.name = "Probe Co"
        tenant_row.feature_flags = {"LOGISTICS": True}

        db = AsyncMock()

        async def _execute(sql, params=None, **kw):
            res = MagicMock()
            res.fetchone = MagicMock(return_value=tenant_row)
            return res

        db.execute = AsyncMock(side_effect=_execute)

        body = FeatureFlagsUpdateRequest(feature_flags={"LOGISTICS": True})
        with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_grant())):
            with patch("shared.permissions.audit.audit_log", new=AsyncMock()):
                resp = await update_feature_flags(tenant_id="t-1", body=body, user=_user(), db=db)

        assert resp is not None
        assert resp.data["changes"] == 0
