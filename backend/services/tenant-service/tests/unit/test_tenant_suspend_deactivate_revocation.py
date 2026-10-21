"""Unit tests: PATCH /{tenant_id}/suspend and PATCH /{tenant_id}/deactivate
each call revoke_tenant_tokens right after their status UPDATE; reactivate
does not (token revocation is a one-way gate — reactivating a tenant must
not restore sessions that were already invalidated)."""

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

from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402 - sys.path/env setup above must run first
from uuid import UUID  # noqa: E402 - sys.path/env setup above must run first

import pytest  # noqa: E402 - sys.path/env setup above must run first

TENANT_ID = "aaaaaaaa-0000-0000-0000-000000000001"

# Patch check_permission to always grant access — these tests focus on the
# revocation side-effect, not RBAC.
_GRANT_ALL = patch(
    "shared.permissions.middleware.check_permission",
    new=AsyncMock(return_value=MagicMock(allowed=True, condition=None)),
)


def _sa_user():
    from dependencies import UserContext

    return UserContext(user_id="sa-1", role="SA", tenant_id=None, warehouse_id=None)


def _db_with_status(status: str) -> AsyncMock:
    db = AsyncMock()
    row = MagicMock()
    row.id = TENANT_ID
    row.name = "Test Co"
    row.status = status
    result = MagicMock()
    result.fetchone = MagicMock(return_value=row)
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.asyncio
async def test_suspend_tenant_revokes_tenant_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    from routers.tenants import suspend_tenant

    mock_revoke = AsyncMock()
    monkeypatch.setattr("routers.tenants.revoke_tenant_tokens", mock_revoke)
    monkeypatch.setattr("routers.tenants._log_tenant_activity", AsyncMock())

    db = _db_with_status("ACTIVE")

    with _GRANT_ALL:
        await suspend_tenant(tenant_id=UUID(TENANT_ID), user=_sa_user(), db=db)

    mock_revoke.assert_awaited_once_with(TENANT_ID)


@pytest.mark.asyncio
async def test_deactivate_tenant_revokes_tenant_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    from routers.tenants import deactivate_tenant

    mock_revoke = AsyncMock()
    monkeypatch.setattr("routers.tenants.revoke_tenant_tokens", mock_revoke)
    monkeypatch.setattr("routers.tenants._log_tenant_activity", AsyncMock())

    db = _db_with_status("ACTIVE")

    with _GRANT_ALL:
        await deactivate_tenant(tenant_id=UUID(TENANT_ID), user=_sa_user(), db=db)

    mock_revoke.assert_awaited_once_with(TENANT_ID)


@pytest.mark.asyncio
async def test_reactivate_tenant_does_not_revoke_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    from routers.tenants import reactivate_tenant

    mock_revoke = AsyncMock()
    monkeypatch.setattr("routers.tenants.revoke_tenant_tokens", mock_revoke)
    monkeypatch.setattr("routers.tenants._log_tenant_activity", AsyncMock())

    db = _db_with_status("SUSPENDED")

    with _GRANT_ALL:
        await reactivate_tenant(tenant_id=UUID(TENANT_ID), user=_sa_user(), db=db)

    mock_revoke.assert_not_called()
