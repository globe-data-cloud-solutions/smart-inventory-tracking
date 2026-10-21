"""PATCH /{tenant_id}/feature-flags — removed in S10 (CLAUDE.md §15): direct
per-tenant feature-flag overrides are replaced by the add-on endpoints
(POST /{tenant_id}/addons, migration 072) so a grant survives a plan change
and can carry a price. The route and its permission stay registered — only
for the CI permission-drift check — and now always 409s USE_ADDONS.

(History: this file previously regression-tested a missing `return` after a
successful update, which fell off the end and returned None, failing
response_model validation with a 500 — CLAUDE.md §15 S9. That code path no
longer exists at all, so that bug is structurally impossible now.)
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("DATABASE_READ_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("ENVIRONMENT", "local")

_TENANT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _TENANT_ROOT not in sys.path:
    sys.path.insert(0, _TENANT_ROOT)

import pytest  # noqa: E402 - sys.path/env setup above must run first
from fastapi import HTTPException  # noqa: E402 - sys.path/env setup above must run first

pytestmark = pytest.mark.asyncio


def _user(role: str = "SA"):
    from dependencies import UserContext

    return UserContext(user_id="u-1", role=role, tenant_id=None, warehouse_id=None)


def _grant():
    from shared.permissions.store import RolePermissionGrant as PermissionGrant

    return PermissionGrant(role="SA", action_id="tenant:manage", grant_type="FULL")


@pytest.mark.unit
class TestUpdateFeatureFlagsAlwaysRejects:
    async def test_always_409_use_addons(self):
        from routers.tenants import update_feature_flags, FeatureFlagsUpdateRequest

        db = AsyncMock()
        body = FeatureFlagsUpdateRequest(feature_flags={"LOGISTICS": True})

        with patch(
            "shared.permissions.middleware.get_role_permission",
            new=AsyncMock(return_value=_grant()),
        ):
            with patch("shared.permissions.audit.audit_log", new=AsyncMock()):
                with pytest.raises(HTTPException) as exc_info:
                    await update_feature_flags(tenant_id="t-1", body=body, user=_user(), db=db)

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["code"] == "USE_ADDONS"
        db.execute.assert_not_called()

    async def test_409_even_with_empty_flags(self):
        """Even a no-op body (empty dict) gets 409 — the route never inspects
        the body before rejecting."""
        from routers.tenants import update_feature_flags, FeatureFlagsUpdateRequest

        db = AsyncMock()
        body = FeatureFlagsUpdateRequest(feature_flags={})

        with patch(
            "shared.permissions.middleware.get_role_permission",
            new=AsyncMock(return_value=_grant()),
        ):
            with patch("shared.permissions.audit.audit_log", new=AsyncMock()):
                with pytest.raises(HTTPException) as exc_info:
                    await update_feature_flags(tenant_id="t-1", body=body, user=_user(), db=db)

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["code"] == "USE_ADDONS"
