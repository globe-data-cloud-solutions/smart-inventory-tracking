"""Router-level tests for GET /api/v1/inventory/lots.

Uses the inv_app fixture (not a fresh `from main import app`) per the
convention established in test_permissions.py / conftest.py.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from dependencies import get_current_user, get_read_db_session


def _mock_full_grant():
    grant = MagicMock()
    grant.grant_type = "FULL"
    return grant


@pytest.fixture
async def lots_client(inv_app, wm_user):
    db = AsyncMock()
    result = MagicMock()
    result.fetchall.return_value = []
    db.execute = AsyncMock(return_value=result)

    async def _db_gen():
        yield db

    inv_app.dependency_overrides[get_current_user] = lambda: wm_user
    inv_app.dependency_overrides[get_read_db_session] = _db_gen
    try:
        with patch(
            "shared.permissions.middleware.get_role_permission",
            new=AsyncMock(return_value=_mock_full_grant()),
        ), patch("shared.permissions.middleware.audit_log", new=AsyncMock()):
            async with AsyncClient(
                transport=ASGITransport(app=inv_app), base_url="http://test"
            ) as ac:
                yield ac
    finally:
        inv_app.dependency_overrides.clear()


@pytest.mark.unit
class TestLotsRouterLimit:

    async def test_limit_max_1000_enforced(self, lots_client) -> None:
        resp = await lots_client.get("/api/v1/inventory/lots", params={"limit": 1001})
        assert resp.status_code == 422

    async def test_limit_at_1000_is_allowed(self, lots_client) -> None:
        resp = await lots_client.get("/api/v1/inventory/lots", params={"limit": 1000})
        assert resp.status_code == 200
