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
    def test_local_dev_auth_returns_valid_jwt(self) -> None:
        """dev_email in local mode returns a signed JWT with the correct seeded claims."""
        resp = client.post(
            "/api/v1/auth/token",
            json={"dev_email": "north.wm@addis-water.com"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0

        payload = jwt.decode(data["access_token"], _SECRET, algorithms=[_ALG])
        assert payload["sub"]          == "00000001-aw03-0000-0000-000000000001"
        assert payload["role"]         == "WM"
        assert payload["tenant_id"]    == "10000001-0000-0000-0000-000000000001"
        assert payload["warehouse_id"] == "20000001-aw00-0000-0000-000000000002"
        assert "exp" in payload
        assert "iat" in payload

    def test_dev_email_case_insensitive(self) -> None:
        """dev_email lookup is case-insensitive."""
        resp = client.post(
            "/api/v1/auth/token",
            json={"dev_email": "North.WM@Addis-Water.COM"},
        )
        assert resp.status_code == 200
        payload = jwt.decode(resp.json()["access_token"], _SECRET, algorithms=[_ALG])
        assert payload["role"] == "WM"

    def test_dev_email_nm_claims(self) -> None:
        """NM user at Main Production Center gets the correct warehouse_id claim.

        production@addis-water.com is seeded as NM assigned to the Main Production Center
        (20000001-aw00-0000-0000-000000000001). NM users CAN have a warehouse_id when
        they are facility-level managers, unlike TA/SA who never have one.
        """
        resp = client.post(
            "/api/v1/auth/token",
            json={"dev_email": "production@addis-water.com"},
        )
        assert resp.status_code == 200
        payload = jwt.decode(resp.json()["access_token"], _SECRET, algorithms=[_ALG])
        assert payload["role"]         == "NM"
        assert payload["warehouse_id"] == "20000001-aw00-0000-0000-000000000001"
        assert payload["tenant_id"]    == "10000001-0000-0000-0000-000000000001"

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

    def test_muger_cement_wm_claims(self) -> None:
        """Muger Cement WM gets the correct tenant_id and warehouse_id."""
        resp = client.post(
            "/api/v1/auth/token",
            json={"dev_email": "kombolcha.wm@muger-cement.com"},
        )
        assert resp.status_code == 200
        payload = jwt.decode(resp.json()["access_token"], _SECRET, algorithms=[_ALG])
        assert payload["sub"]          == "00000002-mc04-0000-0000-000000000001"
        assert payload["tenant_id"]    == "10000002-0000-0000-0000-000000000001"
        assert payload["warehouse_id"] == "20000002-mc00-0000-0000-000000000003"
