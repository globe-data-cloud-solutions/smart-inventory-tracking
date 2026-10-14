"""Near-expiry window as a tenant setting (tenants.near_expiry_days, migration 089).

Covers services/lot_expiry_service.get_near_expiry_days / set_near_expiry_days
and the routes in routers/lots.py that read or write it:
GET /inventory/lots, GET /inventory/lots/expiry-alerts (window falls back to
the tenant value; an explicit param wins) and GET/PUT
/inventory/lots/expiry-settings.

Uses the inv_app fixture (not a fresh `from main import app`) per conftest.py.
RBAC is driven by a small grant table mirroring seed_permissions.py for the
two roles used here.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from dependencies import get_current_user, get_db_session, get_read_db_session
from services.lot_expiry_service import get_near_expiry_days, set_near_expiry_days

TENANT_ID = "10000000-0000-0000-0000-000000000001"

# (role, action) pairs granted — mirrors ROLE_PERMISSION_MATRIX for TA and NM.
_GRANTS = {
    ("TA", "tenant:configure"), ("TA", "report:expiry_alerts"),
    ("TA", "inventory:view_balance"),
    ("NM", "report:expiry_alerts"), ("NM", "inventory:view_balance"),
}

_EMPTY_ALERTS = {
    "window_days": 0,
    "counts": {"expired": 0, "expiring": 0, "no_expiry": 0},
    "items": [],
}


def _result(row):
    r = MagicMock()
    r.fetchone.return_value = row
    r.fetchall.return_value = []
    return r


def _session(tenant_row):
    """execute() returns tenant_row for SELECTs, None-row results for writes."""
    async def _execute(stmt, params=None):
        if str(stmt).lstrip().startswith("SELECT near_expiry_days"):
            return _result(tenant_row)
        return _result(None)

    s = MagicMock()
    s.execute = AsyncMock(side_effect=_execute)
    s.commit = AsyncMock()
    s.rollback = AsyncMock()
    return s


def _sqls(session, prefix):
    return [c for c in session.execute.call_args_list
            if str(c.args[0]).lstrip().startswith(prefix)]


def _user(role):
    return SimpleNamespace(user_id=f"u-{role.lower()}", tenant_id=TENANT_ID, role=role,
                           warehouse_id=None, region_id=None)


async def _grant(role, action_id):
    if (role, action_id) not in _GRANTS:
        return None
    g = MagicMock()
    g.grant_type = "FULL"
    return g


@pytest.fixture
def make_client(inv_app):
    """make_client(role, session) -> AsyncClient context with RBAC from _GRANTS."""
    def _make(role, session):
        async def _db_gen():
            yield session

        inv_app.dependency_overrides[get_current_user] = lambda: _user(role)
        inv_app.dependency_overrides[get_db_session] = _db_gen
        inv_app.dependency_overrides[get_read_db_session] = _db_gen
        return AsyncClient(transport=ASGITransport(app=inv_app), base_url="http://test")

    with patch(
        "shared.permissions.middleware.get_role_permission", new=AsyncMock(side_effect=_grant)
    ), patch("shared.permissions.middleware.audit_log", new=AsyncMock()):
        try:
            yield _make
        finally:
            inv_app.dependency_overrides.clear()


@pytest.mark.unit
class TestGetNearExpiryDaysHelper:

    async def test_returns_tenant_value(self) -> None:
        s = _session(MagicMock(near_expiry_days=45))
        assert await get_near_expiry_days(s, TENANT_ID) == 45
        assert _sqls(s, "SELECT near_expiry_days")[0].args[1] == {"tid": TENANT_ID}

    async def test_none_tenant_is_30_without_query(self) -> None:
        s = _session(MagicMock(near_expiry_days=45))
        assert await get_near_expiry_days(s, None) == 30
        s.execute.assert_not_called()

    async def test_no_row_is_30(self) -> None:
        assert await get_near_expiry_days(_session(None), TENANT_ID) == 30


@pytest.mark.unit
class TestSetNearExpiryDaysService:

    async def test_updates_and_audits_in_same_session(self) -> None:
        s = _session(MagicMock(near_expiry_days=30))
        out = await set_near_expiry_days(s, TENANT_ID, 60, _user("TA"))
        assert out == 60
        updates = _sqls(s, "UPDATE tenants")
        assert len(updates) == 1
        assert updates[0].args[1] == {"d": 60, "tid": TENANT_ID}
        audits = _sqls(s, "INSERT INTO audit_logs")
        assert len(audits) == 1
        assert "tenant:near_expiry_days_update" in str(audits[0].args[0])
        ctx = audits[0].args[1]["ctx"]
        assert '"old_near_expiry_days": 30' in ctx
        assert '"new_near_expiry_days": 60' in ctx


@pytest.mark.unit
class TestLotRoutesFollowSetting:

    async def test_list_lots_no_param_uses_tenant_value(self, make_client) -> None:
        s = _session(MagicMock(near_expiry_days=45))
        with patch("routers.lots.get_lots", new=AsyncMock(return_value=[])) as gl:
            async with make_client("NM", s) as c:
                resp = await c.get("/api/v1/inventory/lots")
        assert resp.status_code == 200
        assert gl.await_args.kwargs["expiring_within_days"] == 45

    async def test_list_lots_explicit_param_wins(self, make_client) -> None:
        s = _session(MagicMock(near_expiry_days=45))
        with patch("routers.lots.get_lots", new=AsyncMock(return_value=[])) as gl:
            async with make_client("NM", s) as c:
                resp = await c.get("/api/v1/inventory/lots", params={"expiring_within_days": 7})
        assert resp.status_code == 200
        assert gl.await_args.kwargs["expiring_within_days"] == 7

    async def test_expiry_alerts_no_param_uses_tenant_value(self, make_client) -> None:
        s = _session(MagicMock(near_expiry_days=45))
        with patch(
            "routers.lots.get_expiry_alerts", new=AsyncMock(return_value=_EMPTY_ALERTS)
        ) as ga:
            async with make_client("NM", s) as c:
                resp = await c.get("/api/v1/inventory/lots/expiry-alerts")
        assert resp.status_code == 200
        assert ga.await_args.kwargs["within_days"] == 45

    async def test_expiry_alerts_explicit_param_wins(self, make_client) -> None:
        s = _session(MagicMock(near_expiry_days=45))
        with patch(
            "routers.lots.get_expiry_alerts", new=AsyncMock(return_value=_EMPTY_ALERTS)
        ) as ga:
            async with make_client("NM", s) as c:
                resp = await c.get(
                    "/api/v1/inventory/lots/expiry-alerts", params={"within_days": 90}
                )
        assert resp.status_code == 200
        assert ga.await_args.kwargs["within_days"] == 90


@pytest.mark.unit
class TestExpirySettingsEndpoints:

    URL = "/api/v1/inventory/lots/expiry-settings"

    async def test_get_returns_stored_value(self, make_client) -> None:
        s = _session(MagicMock(near_expiry_days=21))
        async with make_client("NM", s) as c:
            resp = await c.get(self.URL)
        assert resp.status_code == 200
        assert resp.json()["data"] == {"near_expiry_days": 21}

    async def test_put_valid_updates_and_audits(self, make_client) -> None:
        s = _session(MagicMock(near_expiry_days=30))
        async with make_client("TA", s) as c:
            resp = await c.put(self.URL, json={"near_expiry_days": 60})
        assert resp.status_code == 200
        assert resp.json()["data"] == {"near_expiry_days": 60}
        assert len(_sqls(s, "UPDATE tenants")) == 1
        assert len(_sqls(s, "INSERT INTO audit_logs")) == 1

    @pytest.mark.parametrize("bad", [0, 366])
    async def test_put_out_of_range_422(self, make_client, bad) -> None:
        s = _session(MagicMock(near_expiry_days=30))
        async with make_client("TA", s) as c:
            resp = await c.put(self.URL, json={"near_expiry_days": bad})
        assert resp.status_code == 422
        assert not _sqls(s, "UPDATE tenants")

    async def test_put_without_tenant_configure_403(self, make_client) -> None:
        s = _session(MagicMock(near_expiry_days=30))
        async with make_client("NM", s) as c:
            resp = await c.put(self.URL, json={"near_expiry_days": 60})
        assert resp.status_code == 403
        assert not _sqls(s, "UPDATE tenants")
