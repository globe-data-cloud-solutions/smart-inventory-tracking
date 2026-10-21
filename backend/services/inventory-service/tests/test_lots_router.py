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
    result.fetchone.return_value = None  # no tenants row -> default window 30
    db.execute = AsyncMock(return_value=result)

    async def _db_gen():
        yield db

    inv_app.dependency_overrides[get_current_user] = lambda: wm_user
    inv_app.dependency_overrides[get_read_db_session] = _db_gen
    try:
        with (
            patch(
                "shared.permissions.middleware.get_role_permission",
                new=AsyncMock(return_value=_mock_full_grant()),
            ),
            patch("shared.permissions.middleware.audit_log", new=AsyncMock()),
        ):
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

    async def test_expiring_within_days_bounds(self, lots_client) -> None:
        url = "/api/v1/inventory/lots"
        assert (await lots_client.get(url, params={"expiring_within_days": 0})).status_code == 422
        assert (await lots_client.get(url, params={"expiring_within_days": 366})).status_code == 422
        assert (await lots_client.get(url, params={"expiring_within_days": 365})).status_code == 200


@pytest.mark.unit
class TestExpiryAlertsRouter:
    async def test_within_days_bounds(self, lots_client) -> None:
        url = "/api/v1/inventory/lots/expiry-alerts"
        assert (await lots_client.get(url, params={"within_days": 0})).status_code == 422
        assert (await lots_client.get(url, params={"within_days": 366})).status_code == 422
        assert (await lots_client.get(url, params={"within_days": 365})).status_code == 200

    async def test_default_returns_empty_payload(self, lots_client) -> None:
        resp = await lots_client.get("/api/v1/inventory/lots/expiry-alerts")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["window_days"] == 30
        assert data["items"] == []
        assert data["counts"] == {"expired": 0, "expiring": 0, "no_expiry": 0}

    async def test_own_warehouse_allowed(self, lots_client) -> None:
        resp = await lots_client.get(
            "/api/v1/inventory/lots/expiry-alerts",
            params={"warehouse_id": "20000000-0000-0000-0000-000000000001"},
        )
        assert resp.status_code == 200

    async def test_facility_scoped_user_denied_other_warehouse(self, lots_client) -> None:
        """WM scoped to WAREHOUSE_A requesting a warehouse outside their node -> 403."""
        resp = await lots_client.get(
            "/api/v1/inventory/lots/expiry-alerts",
            params={"warehouse_id": "20000000-0000-0000-0000-0000000000ff"},
        )
        assert resp.status_code == 403


@pytest.fixture
async def patch_client(inv_app, wm_user):
    """WM client against the write session, RBAC grant controlled per test."""
    from dependencies import get_db_session

    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())

    async def _db_gen():
        yield db

    inv_app.dependency_overrides[get_current_user] = lambda: wm_user
    inv_app.dependency_overrides[get_db_session] = _db_gen
    try:
        async with AsyncClient(transport=ASGITransport(app=inv_app), base_url="http://test") as ac:
            yield ac
    finally:
        inv_app.dependency_overrides.clear()


LOT_ID = "30000000-0000-0000-0000-000000000001"


@pytest.mark.unit
class TestSetLotExpiryRouter:
    url = f"/api/v1/inventory/lots/{LOT_ID}/expiry"

    async def _patch(self, client, body):
        with (
            patch(
                "shared.permissions.middleware.get_role_permission",
                new=AsyncMock(return_value=_mock_full_grant()),
            ),
            patch("shared.permissions.middleware.audit_log", new=AsyncMock()),
        ):
            return await client.patch(self.url, json=body)

    async def test_missing_expiry_date_is_422(self, patch_client) -> None:
        assert (await self._patch(patch_client, {})).status_code == 422

    async def test_bad_date_is_422(self, patch_client) -> None:
        assert (await self._patch(patch_client, {"expiry_date": "not-a-date"})).status_code == 422

    async def test_extra_field_is_422(self, patch_client) -> None:
        body = {"expiry_date": "2030-01-01", "lot_number": "X"}
        assert (await self._patch(patch_client, body)).status_code == 422

    async def test_role_without_product_update_is_403(self, patch_client) -> None:
        with (
            patch(
                "shared.permissions.middleware.get_role_permission",
                new=AsyncMock(return_value=None),
            ),
            patch("shared.permissions.middleware.audit_log", new=AsyncMock()),
        ):
            resp = await patch_client.patch(self.url, json={"expiry_date": "2030-01-01"})
        assert resp.status_code == 403
