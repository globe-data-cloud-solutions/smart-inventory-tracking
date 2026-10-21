"""Unit tests for auth-service email verification endpoints (S4):
POST /verify-email, POST /resend-verification, and /token's
EMAIL_NOT_VERIFIED gate. DB and rate-limiting are mocked — no real
connections required.

sys.path note: mirrors test_auth.py's scoped import so later-running service
tests still see their own bare 'main'/'routers' module names.
"""

from __future__ import annotations

import os
import sys

_AUTH_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_was_on_path = _AUTH_ROOT in sys.path
if _was_on_path:
    # See test_auth.py: editable-install .pth files put every service's root
    # on sys.path permanently at a fixed order — being "already present" isn't
    # enough, it must be FIRST or `from main import app` resolves elsewhere.
    sys.path.remove(_AUTH_ROOT)
sys.path.insert(0, _AUTH_ROOT)

from main import app  # noqa: E402 — auth-service/main.py
import routers.auth as auth_module  # noqa: E402

for _mod in ("main", "routers", "routers.auth", "routers.__init__"):
    sys.modules.pop(_mod, None)
if not _was_on_path:
    try:
        sys.path.remove(_AUTH_ROOT)
    except ValueError:
        pass
# ─────────────────────────────────────────────────────────────────────────────

from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402 - sys.path/env setup above must run first

import pytest  # noqa: E402 - sys.path/env setup above must run first
from fastapi.testclient import TestClient  # noqa: E402 - sys.path/env setup above must run first

client = TestClient(app)


class _FakeLockoutRedis:
    """Minimal in-memory stand-in for the login-lockout GET/INCR/EXPIRE/DELETE
    calls that /token's dev_email path makes on every request."""

    def __init__(self) -> None:
        self.store: dict[str, int] = {}

    async def get(self, key: str):
        return str(self.store[key]) if key in self.store else None

    async def incr(self, key: str) -> int:
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    async def expire(self, key: str, seconds: int) -> None:
        pass

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


@pytest.fixture(autouse=True)
def _no_real_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    import shared.cache.login_lockout as _lockout_mod

    monkeypatch.setattr(_lockout_mod, "get_redis_client", lambda: _FakeLockoutRedis())


def _no_rate_limit():
    return patch.object(auth_module, "rate_limit_hit", new=AsyncMock(return_value=None))


@pytest.mark.unit
class TestVerifyEmail:
    def test_valid_token_returns_200_verified(self) -> None:
        with (
            _no_rate_limit(),
            patch.object(
                auth_module, "consume_verification_token", new=AsyncMock(return_value="user-1")
            ),
        ):
            resp = client.post("/api/v1/auth/verify-email", json={"token": "a-real-token"})
        assert resp.status_code == 200
        assert resp.json() == {"verified": True}

    def test_reused_token_returns_400(self) -> None:
        with (
            _no_rate_limit(),
            patch.object(
                auth_module, "consume_verification_token", new=AsyncMock(return_value=None)
            ),
        ):
            resp = client.post("/api/v1/auth/verify-email", json={"token": "already-used"})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "INVALID_OR_EXPIRED_TOKEN"

    def test_expired_token_returns_400(self) -> None:
        with (
            _no_rate_limit(),
            patch.object(
                auth_module, "consume_verification_token", new=AsyncMock(return_value=None)
            ),
        ):
            resp = client.post("/api/v1/auth/verify-email", json={"token": "expired-token"})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "INVALID_OR_EXPIRED_TOKEN"

    def test_garbage_token_returns_400(self) -> None:
        with (
            _no_rate_limit(),
            patch.object(
                auth_module, "consume_verification_token", new=AsyncMock(return_value=None)
            ),
        ):
            resp = client.post("/api/v1/auth/verify-email", json={"token": "not-a-real-token"})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "INVALID_OR_EXPIRED_TOKEN"


def _fake_db(found_user_id: str | None):
    fake_db = AsyncMock()
    result = MagicMock()
    result.fetchone = MagicMock(return_value=MagicMock(id=found_user_id) if found_user_id else None)
    fake_db.execute = AsyncMock(return_value=result)
    fake_db.__aenter__ = AsyncMock(return_value=fake_db)
    fake_db.__aexit__ = AsyncMock(return_value=None)

    begin_cm = AsyncMock()
    begin_cm.__aenter__ = AsyncMock(return_value=None)
    begin_cm.__aexit__ = AsyncMock(return_value=None)
    fake_db.begin = MagicMock(return_value=begin_cm)
    return fake_db


@pytest.mark.unit
class TestResendVerification:
    def test_unknown_email_and_real_email_return_identical_202_body(self) -> None:
        import shared.db.session as _sess_mod

        with _no_rate_limit(), patch.object(auth_module, "send_verification_email") as mock_send:
            with patch.object(_sess_mod, "AsyncSessionLocal", lambda: _fake_db(None)):
                resp_unknown = client.post(
                    "/api/v1/auth/resend-verification", json={"email": "nobody@probe.local"}
                )
            with (
                patch.object(_sess_mod, "AsyncSessionLocal", lambda: _fake_db("real-user-1")),
                patch.object(
                    auth_module, "issue_verification_token", new=AsyncMock(return_value="raw-token")
                ),
            ):
                resp_real = client.post(
                    "/api/v1/auth/resend-verification", json={"email": "real@probe.local"}
                )

        assert resp_unknown.status_code == 202
        assert resp_real.status_code == 202
        assert resp_unknown.json() == resp_real.json() == {"sent": True}
        # Only the real, unverified user actually triggers a send.
        mock_send.assert_called_once_with("real@probe.local", "raw-token")

    def test_unknown_email_never_calls_send(self) -> None:
        import shared.db.session as _sess_mod

        with (
            _no_rate_limit(),
            patch.object(_sess_mod, "AsyncSessionLocal", lambda: _fake_db(None)),
            patch.object(auth_module, "send_verification_email") as mock_send,
        ):
            resp = client.post(
                "/api/v1/auth/resend-verification", json={"email": "nobody@probe.local"}
            )

        assert resp.status_code == 202
        mock_send.assert_not_called()


@pytest.mark.unit
class TestTokenVerificationGate:
    def _mock_claims(self, email_verified_at):
        async def _mock(email: str, password: object = None) -> dict:
            return {
                "sub": "u-1",
                "email": email.lower(),
                "name": "Probe User",
                "tenant_id": "t-1",
                "tenant_slug": "probe",
                "role": "TA",
                "warehouse_id": None,
                "warehouse_name": None,
                "position_id": None,
                "position_title": "Tenant Administrator",
                "level_number": 1,
                "positions": [],
                "must_reset_password": False,
                "email_verified_at": email_verified_at,
            }

        return _mock

    def test_unverified_user_blocked_when_flag_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EMAIL_VERIFICATION_REQUIRED", "true")
        with patch.object(auth_module, "_lookup_user_with_position", new=self._mock_claims(None)):
            resp = client.post(
                "/api/v1/auth/token", json={"dev_email": "probe@test.com", "dev_password": "x"}
            )
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "EMAIL_NOT_VERIFIED"

    def test_unverified_user_allowed_when_flag_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EMAIL_VERIFICATION_REQUIRED", "false")
        with patch.object(auth_module, "_lookup_user_with_position", new=self._mock_claims(None)):
            resp = client.post(
                "/api/v1/auth/token", json={"dev_email": "probe@test.com", "dev_password": "x"}
            )
        assert resp.status_code == 200

    def test_verified_user_allowed_when_flag_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EMAIL_VERIFICATION_REQUIRED", "true")
        with patch.object(
            auth_module, "_lookup_user_with_position", new=self._mock_claims("2026-01-01T00:00:00Z")
        ):
            resp = client.post(
                "/api/v1/auth/token", json={"dev_email": "probe@test.com", "dev_password": "x"}
            )
        assert resp.status_code == 200
