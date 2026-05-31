"""Unit tests for the auth service — local dev bypass and JWT issuance.

Tests are self-contained (no DB, no Redis, no Cognito).
The auth router is exercised via FastAPI's synchronous TestClient.
JWT_SECRET and ENVIRONMENT are set in conftest.py before any module import.

sys.path note
─────────────
Multiple services share bare package names (main, routers, services, …).
This module adds auth-service root to sys.path ONLY long enough to import
`app` and `auth_module`, then removes it from sys.path and sys.modules so
inventory-service tests that run later see their own versions of those names.
The imported objects themselves keep working because Python function closures
read globals from the MODULE DICT (auth_module.__dict__), not from sys.modules.
"""
from __future__ import annotations

import os
import sys

# ── Scoped sys.path manipulation ──────────────────────────────────────────────
_AUTH_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_was_on_path = _AUTH_ROOT in sys.path
if not _was_on_path:
    sys.path.insert(0, _AUTH_ROOT)

from main import app  # noqa: E402 — auth-service/main.py
import routers.auth as auth_module  # noqa: E402 — auth-service/routers/auth.py

# Remove auth-service's bare module names so later-running service tests
# (inventory-service, product-service) get their own 'main' / 'routers' / 'services'.
for _mod in ("main", "routers", "routers.auth", "routers.__init__"):
    sys.modules.pop(_mod, None)
if not _was_on_path:
    try:
        sys.path.remove(_AUTH_ROOT)
    except ValueError:
        pass
# ─────────────────────────────────────────────────────────────────────────────

import pytest
from fastapi.testclient import TestClient
from jose import jwt

_SECRET = "test-secret-for-unit-tests"
_ALG    = "HS256"

client = TestClient(app)


@pytest.mark.unit
class TestLocalDevAuth:
    def test_local_dev_auth_returns_valid_jwt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """dev_email in local mode returns a signed JWT.

        Mocks _lookup_user_with_position so the test is DB-free.
        SA path: tenant_id=None, role=SA, no warehouse.
        """
        import asyncio

        async def _mock_sa(email: str, password: object = None) -> dict:
            return {
                "sub":                 "sa-001",
                "email":               email.lower(),
                "name":                "System Administrator",
                "tenant_id":           None,
                "tenant_slug":         None,
                "role":                "SA",
                "warehouse_id":        None,
                "warehouse_name":      None,
                "position_id":         None,
                "position_title":      None,
                "level_number":        None,
                "positions":           [],
                "must_reset_password": False,
            }

        monkeypatch.setattr(auth_module, "_lookup_user_with_position", _mock_sa)

        resp = client.post(
            "/api/v1/auth/token",
            json={"dev_email": "smartadmin@smart-inventory.com"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0

        payload = jwt.decode(data["access_token"], _SECRET, algorithms=[_ALG])
        assert payload["role"]         == "SA"
        assert payload["tenant_id"]    is None
        assert payload["warehouse_id"] is None
        assert "exp" in payload
        assert "iat" in payload

    def test_dev_email_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """dev_email lookup is case-insensitive — uppercase email returns same role."""

        async def _mock_sa(email: str, password: object = None) -> dict:
            return {
                "sub":                 "sa-001",
                "email":               email.lower(),
                "name":                "System Administrator",
                "tenant_id":           None,
                "tenant_slug":         None,
                "role":                "SA",
                "warehouse_id":        None,
                "warehouse_name":      None,
                "position_id":         None,
                "position_title":      None,
                "level_number":        None,
                "positions":           [],
                "must_reset_password": False,
            }

        monkeypatch.setattr(auth_module, "_lookup_user_with_position", _mock_sa)

        resp = client.post(
            "/api/v1/auth/token",
            json={"dev_email": "SMARTADMIN@SMART-INVENTORY.COM"},
        )
        assert resp.status_code == 200
        payload = jwt.decode(resp.json()["access_token"], _SECRET, algorithms=[_ALG])
        assert payload["role"] == "SA"

    def test_dev_email_ta_claims(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TA user (system_role='TA', no position) gets role=TA and empty positions list.

        TA users are identified by system_role column, not by a position in the hierarchy.
        The JWT must carry role=TA, warehouse_id=None, and positions=[].
        """

        async def _mock_ta(email: str, password: object = None) -> dict:
            return {
                "sub":                 "ta-001",
                "email":               email.lower(),
                "name":                "Tenant Admin",
                "tenant_id":           "aaaaaaaa-0000-0000-0000-000000000001",
                "tenant_slug":         "acme",
                "role":                "TA",
                "warehouse_id":        None,
                "warehouse_name":      None,
                "position_id":         None,
                "position_title":      "Tenant Administrator",
                "level_number":        1,
                "positions":           [],
                "must_reset_password": False,
            }

        monkeypatch.setattr(auth_module, "_lookup_user_with_position", _mock_ta)

        resp = client.post(
            "/api/v1/auth/token",
            json={"dev_email": "admin@acme.com"},
        )
        assert resp.status_code == 200
        payload = jwt.decode(resp.json()["access_token"], _SECRET, algorithms=[_ALG])
        assert payload["role"]         == "TA"
        assert payload["tenant_id"]    == "aaaaaaaa-0000-0000-0000-000000000001"
        assert payload["warehouse_id"] is None
        assert payload["positions"]    == []

    def test_dev_email_unknown_returns_404(self) -> None:
        """Unknown dev_email returns 404 in local mode."""
        resp = client.post(
            "/api/v1/auth/token",
            json={"dev_email": "nobody@unknown.com"},
        )
        assert resp.status_code == 404

    def test_dev_email_blocked_in_non_local(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """dev_email is rejected with 403 when ENVIRONMENT != 'local'."""
        monkeypatch.setattr(auth_module, "ENVIRONMENT", "production")
        resp = client.post(
            "/api/v1/auth/token",
            json={"dev_email": "north.wm@addis-water.com"},
        )
        assert resp.status_code == 403

    def test_cognito_demo_path_still_works(self) -> None:
        """Existing cognito_token + demo_* path still issues a valid JWT (backward compat)."""
        resp = client.post(
            "/api/v1/auth/token",
            json={
                "cognito_token":    "demo",
                "demo_sub":          "aaaa-1111",
                "demo_role":         "NM",
                "demo_tenant_id":    "tttt-2222",
                "demo_warehouse_id": None,
            },
        )
        assert resp.status_code == 200
        payload = jwt.decode(resp.json()["access_token"], _SECRET, algorithms=[_ALG])
        assert payload["sub"]          == "aaaa-1111"
        assert payload["role"]         == "NM"
        assert payload["tenant_id"]    == "tttt-2222"
        assert payload["warehouse_id"] is None

    def test_empty_body_returns_422(self) -> None:
        """Empty body with neither dev_email nor cognito_token returns 422."""
        resp = client.post("/api/v1/auth/token", json={})
        assert resp.status_code == 422

