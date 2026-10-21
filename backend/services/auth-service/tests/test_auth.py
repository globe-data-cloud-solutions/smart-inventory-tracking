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
if _was_on_path:
    # Editable-install .pth files (pip install -e for every backend/services/*
    # package) put every service's root on sys.path permanently, at a fixed
    # order (alphabetical-ish) — e.g. api-gateway sorts before auth-service.
    # Being "already in sys.path" is therefore not enough; it must be FIRST,
    # or `from main import app` below resolves to api-gateway's main.py instead.
    sys.path.remove(_AUTH_ROOT)
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


def _bearer_for(sub: str) -> dict[str, str]:
    """Build an Authorization header carrying a SMART JWT with the given sub,
    for exercising the authenticated PATCH /password/{user_id} route."""
    token = jwt.encode({"sub": sub}, _SECRET, algorithm=_ALG)
    return {"Authorization": f"Bearer {token}"}


class _FakeRedis:
    """In-memory stand-in for redis.asyncio.Redis — just enough of GET/INCR/
    EXPIRE/DELETE to exercise the login-lockout logic without a real server."""

    def __init__(self) -> None:
        self.store: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return str(self.store[key]) if key in self.store else None

    async def incr(self, key: str) -> int:
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    async def expire(self, key: str, seconds: int) -> None:
        pass  # TTL behavior is Redis's job — not simulated here

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


@pytest.fixture(autouse=True)
def _no_real_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    """Every test in this module gets a fresh in-memory fake Redis client —
    none of them should ever touch a real server. exchange_token's dev_email
    path now calls get_redis_client() on every request (login-lockout check),
    and the email/password path also calls the "login" rate-limit bucket, so
    this must be autouse rather than opt-in per test.

    The lockout helpers live in shared.cache.login_lockout (used by both
    auth-service and tenant-service), and the login rate limit lives in
    shared.cache.rate_limit — both modules hold their own get_redis_client
    binding, so both must be patched to the same fake."""
    fake = _FakeRedis()
    import shared.cache.login_lockout as _lockout_mod
    import shared.cache.rate_limit as _rate_limit_mod
    monkeypatch.setattr(_lockout_mod, "get_redis_client", lambda: fake)
    monkeypatch.setattr(_rate_limit_mod, "get_redis_client", lambda: fake)
    return fake


@pytest.mark.unit
class TestLocalDevAuth:
    def test_local_dev_auth_returns_valid_jwt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """dev_email in local mode returns a signed JWT.

        Mocks _lookup_user_with_position so the test is DB-free.
        SA path: tenant_id=None, role=SA, no warehouse.
        """

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

    def test_au_user_can_login_without_position(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AU user (system_role='AU', no position) gets role=AU and is not blocked
        by the position-required check. Exercises the real _lookup_user_with_position
        logic (not mocked) via a fake DB session, so the fix itself is verified —
        previously this fell through to the position lookup and hit the 403
        'No active position assigned' block."""
        from unittest.mock import AsyncMock, MagicMock

        fake_row = MagicMock()
        fake_row.id                  = "au-001"
        fake_row.email                = "au@acme.com"
        fake_row.full_name            = "Almaz Tesfaye"
        fake_row.tenant_id            = "aaaaaaaa-0000-0000-0000-000000000001"
        fake_row.password_hash        = None
        fake_row.must_reset_password  = False
        fake_row.system_role          = "AU"
        fake_row.is_active            = True
        fake_row.tenant_slug          = "acme"

        fake_result = MagicMock()
        fake_result.fetchone = MagicMock(return_value=fake_row)

        fake_db = AsyncMock()
        fake_db.execute    = AsyncMock(return_value=fake_result)
        fake_db.__aenter__ = AsyncMock(return_value=fake_db)
        fake_db.__aexit__  = AsyncMock(return_value=None)

        import shared.db.session as _sess_mod
        monkeypatch.setattr(_sess_mod, "AsyncSessionLocal", lambda: fake_db)

        resp = client.post("/api/v1/auth/token", json={"dev_email": "au@acme.com"})
        assert resp.status_code == 200, resp.text
        payload = jwt.decode(resp.json()["access_token"], _SECRET, algorithms=[_ALG])
        assert payload["role"]         == "AU"
        assert payload["tenant_id"]    == "aaaaaaaa-0000-0000-0000-000000000001"
        assert payload["warehouse_id"] is None
        assert payload["position_id"]  is None
        assert payload["positions"]    == []

    def test_lm_user_can_login_without_position(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LM user (system_role='LM', no position) gets role=LM — same direct-role
        path as AU/TA, exercised through the real lookup function."""
        from unittest.mock import AsyncMock, MagicMock

        fake_row = MagicMock()
        fake_row.id                  = "lm-001"
        fake_row.email                = "lm@acme.com"
        fake_row.full_name            = "Dawit Alemu"
        fake_row.tenant_id            = "aaaaaaaa-0000-0000-0000-000000000001"
        fake_row.password_hash        = None
        fake_row.must_reset_password  = False
        fake_row.system_role          = "LM"
        fake_row.is_active            = True
        fake_row.tenant_slug          = "acme"

        fake_result = MagicMock()
        fake_result.fetchone = MagicMock(return_value=fake_row)

        fake_db = AsyncMock()
        fake_db.execute    = AsyncMock(return_value=fake_result)
        fake_db.__aenter__ = AsyncMock(return_value=fake_db)
        fake_db.__aexit__  = AsyncMock(return_value=None)

        import shared.db.session as _sess_mod
        monkeypatch.setattr(_sess_mod, "AsyncSessionLocal", lambda: fake_db)

        resp = client.post("/api/v1/auth/token", json={"dev_email": "lm@acme.com"})
        assert resp.status_code == 200, resp.text
        payload = jwt.decode(resp.json()["access_token"], _SECRET, algorithms=[_ALG])
        assert payload["role"]         == "LM"
        assert payload["warehouse_id"] is None
        assert payload["position_id"]  is None
        assert payload["positions"]    == []

    def test_dev_email_unknown_returns_401(self) -> None:
        """Unknown dev_email returns 401 (was 404 before FIX A2).
        Using 401 avoids leaking whether an email exists in the system."""
        resp = client.post(
            "/api/v1/auth/token",
            json={"dev_email": "nobody@unknown.com"},
        )
        assert resp.status_code == 401

    def test_dev_email_blocked_in_non_local(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """dev_email is rejected with 403 when ENVIRONMENT != 'local'."""
        monkeypatch.setattr(auth_module, "ENVIRONMENT", "production")
        resp = client.post(
            "/api/v1/auth/token",
            json={"dev_email": "north.wm@addis-water.com"},
        )
        assert resp.status_code == 403

    def test_email_password_login_success_in_production(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """email+password works in every environment, including production."""
        monkeypatch.setattr(auth_module, "ENVIRONMENT", "production")

        async def _mock_wm(email: str, password: object = None) -> dict:
            return {
                "sub":                 "wm-001",
                "email":               email.lower(),
                "name":                "Warehouse Manager",
                "tenant_id":           "aaaaaaaa-0000-0000-0000-000000000001",
                "tenant_slug":         "acme",
                "role":                "WM",
                "warehouse_id":        "bbbbbbbb-0000-0000-0000-000000000001",
                "warehouse_name":      "WH1",
                "position_id":         "cccccccc-0000-0000-0000-000000000001",
                "position_title":      "Warehouse Manager",
                "level_number":        3,
                "positions":           [],
                "must_reset_password": False,
            }

        monkeypatch.setattr(auth_module, "_lookup_user_with_position", _mock_wm)

        resp = client.post(
            "/api/v1/auth/token",
            json={"email": "wm@acme.com", "password": "Correct@2026"},
        )
        assert resp.status_code == 200, resp.text
        payload = jwt.decode(resp.json()["access_token"], _SECRET, algorithms=[_ALG])
        assert payload["role"]      == "WM"
        assert payload["tenant_id"] == "aaaaaaaa-0000-0000-0000-000000000001"

    def test_email_without_password_returns_422(self) -> None:
        """email provided but password missing/empty returns 422 PASSWORD_REQUIRED."""
        resp = client.post("/api/v1/auth/token", json={"email": "wm@acme.com"})
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "PASSWORD_REQUIRED"

        resp2 = client.post("/api/v1/auth/token", json={"email": "wm@acme.com", "password": ""})
        assert resp2.status_code == 422
        assert resp2.json()["detail"]["code"] == "PASSWORD_REQUIRED"

    def test_email_wrong_password_returns_invalid_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Wrong password on the email path returns the generic 401 INVALID_CREDENTIALS."""

        async def _mock_wrong_password(email: str, password: object = None) -> dict:
            raise auth_module.HTTPException(status_code=401, detail="Invalid password")

        monkeypatch.setattr(auth_module, "_lookup_user_with_position", _mock_wrong_password)

        resp = client.post(
            "/api/v1/auth/token",
            json={"email": "wm@acme.com", "password": "wrong"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"]["code"] == "INVALID_CREDENTIALS"

    def test_email_unknown_returns_invalid_credentials(self) -> None:
        """Unknown email on the email path returns the same generic 401
        INVALID_CREDENTIALS as a wrong password — no account enumeration."""
        resp = client.post(
            "/api/v1/auth/token",
            json={"email": "nobody@unknown.com", "password": "whatever"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"]["code"] == "INVALID_CREDENTIALS"

    def test_cognito_token_only_returns_422(self) -> None:
        """A body with only the removed cognito_token field matches no path — 422."""
        resp = client.post(
            "/api/v1/auth/token",
            json={"cognito_token": "demo"},
        )
        assert resp.status_code == 422

    def test_empty_body_returns_422(self) -> None:
        """Empty body with neither email nor dev_email returns 422."""
        resp = client.post("/api/v1/auth/token", json={})
        assert resp.status_code == 422

    # ── PENDING_SETUP tests (PART B1 / B3) ────────────────────────────────

    def test_must_reset_no_position_gets_jwt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """User with must_reset_password=true and no position gets a PENDING_SETUP
        JWT instead of HTTP 403.  Fixes the catch-22 where new users could never
        reach the change-password page."""

        async def _mock_pending(email: str, password: object = None) -> dict:
            return {
                "sub":                 "user-pending-001",
                "email":               email.lower(),
                "name":                "New User",
                "tenant_id":           "tttt-1111",
                "tenant_slug":         "test-tenant",
                "role":                "PENDING_SETUP",
                "warehouse_id":        None,
                "warehouse_name":      None,
                "position_id":         None,
                "position_title":      None,
                "level_number":        None,
                "positions":           [],
                "must_reset_password": True,
            }

        monkeypatch.setattr(auth_module, "_lookup_user_with_position", _mock_pending)

        resp = client.post(
            "/api/v1/auth/token",
            json={"dev_email": "newuser@test.com", "dev_password": "TempPass@2026"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["must_reset_password"] is True

    def test_pending_setup_role_in_jwt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The JWT returned for a PENDING_SETUP user must carry role=PENDING_SETUP
        so the frontend can recognise and redirect appropriately."""

        async def _mock_pending(email: str, password: object = None) -> dict:
            return {
                "sub":                 "user-pending-002",
                "email":               email.lower(),
                "name":                "Pending User",
                "tenant_id":           "tttt-2222",
                "tenant_slug":         "demo-tenant",
                "role":                "PENDING_SETUP",
                "warehouse_id":        None,
                "warehouse_name":      None,
                "position_id":         None,
                "position_title":      None,
                "level_number":        None,
                "positions":           [],
                "must_reset_password": True,
            }

        monkeypatch.setattr(auth_module, "_lookup_user_with_position", _mock_pending)

        resp = client.post("/api/v1/auth/token", json={"dev_email": "pending@demo.com"})
        assert resp.status_code == 200

        body    = resp.json()
        token   = body["access_token"]
        payload = jwt.decode(token, _SECRET, algorithms=[_ALG])
        # role is in the JWT payload
        assert payload["role"]         == "PENDING_SETUP"
        assert payload["warehouse_id"] is None
        assert payload["positions"]    == []
        # must_reset_password is in the TokenResponse body (not in the JWT)
        assert body["must_reset_password"] is True

    def test_password_change_clears_reset_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """PATCH /password/{id} with must_reset=true and NO current_password must
        succeed (current_password is optional for PENDING_SETUP users) and the
        endpoint should not return 401."""
        from unittest.mock import AsyncMock, MagicMock

        monkeypatch.setattr(auth_module, "ENVIRONMENT", "local")

        # Build a fake DB row: must_reset=True, password_hash=some_hash
        import bcrypt as _bcrypt
        fake_hash = _bcrypt.hashpw(b"TempPass@2026", _bcrypt.gensalt()).decode()
        fake_row  = MagicMock()
        fake_row.id                 = "user-pending-003"
        fake_row.password_hash      = fake_hash
        fake_row.must_reset_password = True

        fake_result = MagicMock()
        fake_result.fetchone = MagicMock(return_value=fake_row)

        fake_db = AsyncMock()
        fake_db.execute   = AsyncMock(return_value=fake_result)
        fake_db.commit    = AsyncMock()
        fake_db.__aenter__ = AsyncMock(return_value=fake_db)
        fake_db.__aexit__  = AsyncMock(return_value=None)

        import shared.db.session as _sess_mod
        monkeypatch.setattr(_sess_mod, "AsyncSessionLocal", lambda: fake_db)

        # No current_password supplied — must NOT return 401
        resp = client.patch(
            "/api/v1/auth/password/user-pending-003",
            json={
                "user_id":     "user-pending-003",
                "new_password": "NewSecure@2026!",
                # current_password intentionally omitted
            },
            headers=_bearer_for("user-pending-003"),
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        assert resp.json()["success"] is True

    def test_change_password_no_bearer_returns_401(self) -> None:
        """PATCH /password/{id} with no Authorization header returns 401."""
        resp = client.patch(
            "/api/v1/auth/password/some-user-id",
            json={"user_id": "some-user-id", "new_password": "NewSecure@2026!"},
        )
        assert resp.status_code == 401

    def test_change_password_bearer_for_other_user_returns_403(self) -> None:
        """A valid bearer token whose sub != the path user_id returns 403."""
        resp = client.patch(
            "/api/v1/auth/password/some-user-id",
            json={"user_id": "some-user-id", "new_password": "NewSecure@2026!"},
            headers=_bearer_for("a-different-user-id"),
        )
        assert resp.status_code == 403

    def test_change_password_wrong_current_password_returns_401(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A normal (non-must_reset) user supplying the wrong current_password
        gets 401, even with ENVIRONMENT=production."""
        from unittest.mock import AsyncMock, MagicMock

        monkeypatch.setattr(auth_module, "ENVIRONMENT", "production")

        import bcrypt as _bcrypt
        fake_hash = _bcrypt.hashpw(b"ActualPass@2026", _bcrypt.gensalt()).decode()
        fake_row  = MagicMock()
        fake_row.id                  = "user-normal-001"
        fake_row.password_hash       = fake_hash
        fake_row.must_reset_password = False

        fake_result = MagicMock()
        fake_result.fetchone = MagicMock(return_value=fake_row)

        fake_db = AsyncMock()
        fake_db.execute    = AsyncMock(return_value=fake_result)
        fake_db.__aenter__ = AsyncMock(return_value=fake_db)
        fake_db.__aexit__  = AsyncMock(return_value=None)

        import shared.db.session as _sess_mod
        monkeypatch.setattr(_sess_mod, "AsyncSessionLocal", lambda: fake_db)

        resp = client.patch(
            "/api/v1/auth/password/user-normal-001",
            json={
                "user_id":          "user-normal-001",
                "current_password": "wrong",
                "new_password":     "NewSecure@2026!",
            },
            headers=_bearer_for("user-normal-001"),
        )
        assert resp.status_code == 401

    def test_change_password_works_in_production(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A normal user with the correct current_password can change it with
        ENVIRONMENT=production — the local-only gate is gone."""
        from unittest.mock import AsyncMock, MagicMock

        monkeypatch.setattr(auth_module, "ENVIRONMENT", "production")

        import bcrypt as _bcrypt
        fake_hash = _bcrypt.hashpw(b"ActualPass@2026", _bcrypt.gensalt()).decode()
        fake_row  = MagicMock()
        fake_row.id                  = "user-normal-002"
        fake_row.password_hash       = fake_hash
        fake_row.must_reset_password = False

        fake_result = MagicMock()
        fake_result.fetchone = MagicMock(return_value=fake_row)

        fake_db = AsyncMock()
        fake_db.execute    = AsyncMock(return_value=fake_result)
        fake_db.commit     = AsyncMock()
        fake_db.__aenter__ = AsyncMock(return_value=fake_db)
        fake_db.__aexit__  = AsyncMock(return_value=None)

        import shared.db.session as _sess_mod
        monkeypatch.setattr(_sess_mod, "AsyncSessionLocal", lambda: fake_db)

        resp = client.patch(
            "/api/v1/auth/password/user-normal-002",
            json={
                "user_id":          "user-normal-002",
                "current_password": "ActualPass@2026",
                "new_password":     "NewSecure@2026!",
            },
            headers=_bearer_for("user-normal-002"),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["success"] is True

    def test_change_password_revokes_user_tokens(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A successful password change calls revoke_user_tokens for that user
        so every previously-issued JWT stops working."""
        from unittest.mock import AsyncMock, MagicMock

        monkeypatch.setattr(auth_module, "ENVIRONMENT", "production")

        import bcrypt as _bcrypt
        fake_hash = _bcrypt.hashpw(b"ActualPass@2026", _bcrypt.gensalt()).decode()
        fake_row  = MagicMock()
        fake_row.id                  = "user-normal-003"
        fake_row.password_hash       = fake_hash
        fake_row.must_reset_password = False

        fake_result = MagicMock()
        fake_result.fetchone = MagicMock(return_value=fake_row)

        fake_db = AsyncMock()
        fake_db.execute    = AsyncMock(return_value=fake_result)
        fake_db.commit     = AsyncMock()
        fake_db.__aenter__ = AsyncMock(return_value=fake_db)
        fake_db.__aexit__  = AsyncMock(return_value=None)

        import shared.db.session as _sess_mod
        monkeypatch.setattr(_sess_mod, "AsyncSessionLocal", lambda: fake_db)

        mock_revoke = AsyncMock()
        monkeypatch.setattr(auth_module, "revoke_user_tokens", mock_revoke)

        resp = client.patch(
            "/api/v1/auth/password/user-normal-003",
            json={
                "user_id":          "user-normal-003",
                "current_password": "ActualPass@2026",
                "new_password":     "NewSecure@2026!",
            },
            headers=_bearer_for("user-normal-003"),
        )
        assert resp.status_code == 200, resp.text
        mock_revoke.assert_awaited_once_with("user-normal-003")


@pytest.mark.unit
class TestLoginAttemptLimiting:
    """Fix 3 — failed dev_email logins are tracked in Redis; 5 failures lock
    the email out for 15 minutes (429 + Retry-After). A successful login
    resets the counter. Redis is faked (_FakeRedis) — never touches a real
    server, consistent with this file's "no DB, no Redis, no Cognito" design."""

    def test_login_lockout_after_5_attempts(
        self, monkeypatch: pytest.MonkeyPatch, _no_real_redis: _FakeRedis
    ) -> None:
        async def _mock_wrong_password(email: str, password: object = None) -> dict:
            raise auth_module.HTTPException(status_code=401, detail="Invalid password")

        monkeypatch.setattr(auth_module, "_lookup_user_with_position", _mock_wrong_password)

        for _ in range(5):
            resp = client.post(
                "/api/v1/auth/token",
                json={"dev_email": "locktest@acme.com", "dev_password": "wrong"},
            )
            assert resp.status_code == 401

        # The 6th attempt is blocked — 5 failures already recorded.
        resp = client.post(
            "/api/v1/auth/token",
            json={"dev_email": "locktest@acme.com", "dev_password": "wrong"},
        )
        assert resp.status_code == 429
        assert resp.json()["detail"]["code"] == "TOO_MANY_ATTEMPTS"

    def test_lockout_includes_retry_after_header(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _mock_wrong_password(email: str, password: object = None) -> dict:
            raise auth_module.HTTPException(status_code=401, detail="Invalid password")

        monkeypatch.setattr(auth_module, "_lookup_user_with_position", _mock_wrong_password)

        for _ in range(5):
            client.post(
                "/api/v1/auth/token",
                json={"dev_email": "locktest2@acme.com", "dev_password": "wrong"},
            )

        resp = client.post(
            "/api/v1/auth/token",
            json={"dev_email": "locktest2@acme.com", "dev_password": "wrong"},
        )
        assert resp.status_code == 429
        assert resp.headers["retry-after"] == "900"

    def test_successful_login_resets_counter(
        self, monkeypatch: pytest.MonkeyPatch, _no_real_redis: _FakeRedis
    ) -> None:
        """3 wrong → 1 correct (resets counter) → wrong again → still not locked
        out, because the successful login cleared the count back to zero."""
        call_log: list[str] = []

        async def _mock_lookup(email: str, password: object = None) -> dict | None:
            if password == "correct":
                call_log.append("success")
                return {
                    "sub": "u-1", "email": email, "name": "Test User",
                    "tenant_id": "aaaaaaaa-0000-0000-0000-000000000001",
                    "tenant_slug": "acme", "role": "WM",
                    "warehouse_id": "bbbbbbbb-0000-0000-0000-000000000001",
                    "warehouse_name": "WH1", "position_id": "cccccccc-0000-0000-0000-000000000001",
                    "position_title": "Warehouse Manager", "level_number": 3,
                    "positions": [], "must_reset_password": False,
                }
            call_log.append("fail")
            raise auth_module.HTTPException(status_code=401, detail="Invalid password")

        monkeypatch.setattr(auth_module, "_lookup_user_with_position", _mock_lookup)
        fake_redis = _no_real_redis

        email = "resettest@acme.com"
        for _ in range(3):
            resp = client.post("/api/v1/auth/token", json={"dev_email": email, "dev_password": "wrong"})
            assert resp.status_code == 401
        assert fake_redis.store[auth_module._login_attempts_key(email)] == 3

        resp = client.post("/api/v1/auth/token", json={"dev_email": email, "dev_password": "correct"})
        assert resp.status_code == 200
        assert auth_module._login_attempts_key(email) not in fake_redis.store

        # One more wrong attempt after the reset — should NOT be locked out.
        resp = client.post("/api/v1/auth/token", json={"dev_email": email, "dev_password": "wrong"})
        assert resp.status_code == 401


@pytest.mark.unit
class TestLoginPerIpRateLimit:
    """B3: the "login" rate-limit bucket is hit on the email/password path of
    /auth/token (per-IP, before the lockout check) and never on the dev_email
    path — dev_email is a local-only scripts/e2e shortcut, not a public,
    attacker-reachable surface."""

    def test_email_password_path_429_once_login_bucket_exhausted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _mock_wrong_password(email: str, password: object = None) -> dict:
            raise auth_module.HTTPException(status_code=401, detail="Invalid password")

        monkeypatch.setattr(auth_module, "_lookup_user_with_position", _mock_wrong_password)

        async def _mock_rate_limit_hit(bucket: str, key: str) -> None:
            if bucket == "login":
                raise auth_module.HTTPException(
                    status_code=429,
                    detail={"code": "RATE_LIMITED", "message": "Too many requests. Please try again later."},
                )

        monkeypatch.setattr(auth_module, "rate_limit_hit", _mock_rate_limit_hit)

        resp = client.post(
            "/api/v1/auth/token",
            json={"email": "ratelimited@acme.com", "password": "wrong"},
        )
        assert resp.status_code == 429
        assert resp.json()["detail"]["code"] == "RATE_LIMITED"

    def test_dev_email_path_is_never_rate_limited(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """dev_email must not call the "login" bucket at all — asserting via a
        rate_limit_hit mock that always raises 429 makes this unambiguous: if
        the dev_email path ever starts hitting it, this test fails."""

        async def _mock_pending(email: str, password: object = None) -> dict:
            return {
                "sub": "u-dev", "email": email, "name": "Dev User",
                "tenant_id": "aaaaaaaa-0000-0000-0000-000000000001",
                "tenant_slug": "acme", "role": "WM",
                "warehouse_id": "bbbbbbbb-0000-0000-0000-000000000001",
                "warehouse_name": "WH1", "position_id": "cccccccc-0000-0000-0000-000000000001",
                "position_title": "Warehouse Manager", "level_number": 3,
                "positions": [], "must_reset_password": False,
            }

        async def _mock_rate_limit_hit_always_429(bucket: str, key: str) -> None:
            raise auth_module.HTTPException(status_code=429, detail={"code": "RATE_LIMITED"})

        monkeypatch.setattr(auth_module, "_lookup_user_with_position", _mock_pending)
        monkeypatch.setattr(auth_module, "rate_limit_hit", _mock_rate_limit_hit_always_429)

        resp = client.post(
            "/api/v1/auth/token",
            json={"dev_email": "devpath@acme.com"},
        )
        assert resp.status_code == 200, resp.text


@pytest.mark.unit
class TestSuspendedTenantPasswordOrdering:
    """Password must be verified BEFORE the tenant SUSPENDED/DEACTIVATED check,
    so a 403 (which confirms the tenant's existence and status) is only ever
    returned to a caller who has already proven they know the password.
    Exercises the real _lookup_user_with_position via a fake DB — not mocked."""

    def _fake_db_for_suspended_tenant(self):
        import bcrypt
        from unittest.mock import AsyncMock, MagicMock

        fake_row = MagicMock()
        fake_row.id                 = "ta-001"
        fake_row.email               = "ta@suspended.com"
        fake_row.full_name           = "Suspended TA"
        fake_row.tenant_id           = "aaaaaaaa-0000-0000-0000-000000000099"
        fake_row.password_hash       = bcrypt.hashpw(b"CorrectPass123", bcrypt.gensalt()).decode()
        fake_row.must_reset_password = False
        fake_row.system_role         = "TA"
        fake_row.is_active           = True
        fake_row.email_verified_at   = None
        fake_row.tenant_slug         = "suspended-co"
        fake_row.tenant_active       = True
        fake_row.tenant_status       = "SUSPENDED"

        fake_result = MagicMock()
        fake_result.fetchone = MagicMock(return_value=fake_row)

        fake_db = AsyncMock()
        fake_db.execute    = AsyncMock(return_value=fake_result)
        fake_db.__aenter__ = AsyncMock(return_value=fake_db)
        fake_db.__aexit__  = AsyncMock(return_value=None)
        return fake_db

    def test_wrong_password_returns_401_not_403(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import shared.db.session as _sess_mod
        monkeypatch.setattr(_sess_mod, "AsyncSessionLocal", lambda: self._fake_db_for_suspended_tenant())

        resp = client.post(
            "/api/v1/auth/token",
            json={"email": "ta@suspended.com", "password": "WrongPassword"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"]["code"] == "INVALID_CREDENTIALS"

    def test_right_password_returns_403_tenant_suspended(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import shared.db.session as _sess_mod
        monkeypatch.setattr(_sess_mod, "AsyncSessionLocal", lambda: self._fake_db_for_suspended_tenant())

        resp = client.post(
            "/api/v1/auth/token",
            json={"email": "ta@suspended.com", "password": "CorrectPass123"},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "TENANT_SUSPENDED"

