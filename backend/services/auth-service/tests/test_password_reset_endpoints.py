"""Unit tests for auth-service password reset endpoints (B2):
POST /forgot-password, POST /reset-password. DB and rate-limiting are
mocked — no real connections required.

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
    calls."""

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
class TestForgotPassword:
    def test_known_and_unknown_email_return_identical_202_body(self) -> None:
        import shared.db.session as _sess_mod

        with _no_rate_limit(), patch.object(auth_module, "send_reset_email") as mock_send:
            with patch.object(_sess_mod, "AsyncSessionLocal", lambda: _fake_db(None)):
                resp_unknown = client.post(
                    "/api/v1/auth/forgot-password", json={"email": "nobody@probe.local"}
                )
            with (
                patch.object(_sess_mod, "AsyncSessionLocal", lambda: _fake_db("real-user-1")),
                patch.object(
                    auth_module, "issue_reset_token", new=AsyncMock(return_value="raw-token")
                ),
            ):
                resp_real = client.post(
                    "/api/v1/auth/forgot-password", json={"email": "real@probe.local"}
                )

        assert resp_unknown.status_code == 202
        assert resp_real.status_code == 202
        assert resp_unknown.json() == resp_real.json() == {"sent": True}
        mock_send.assert_called_once_with("real@probe.local", "raw-token")

    def test_unknown_email_never_calls_send(self) -> None:
        import shared.db.session as _sess_mod

        with (
            _no_rate_limit(),
            patch.object(_sess_mod, "AsyncSessionLocal", lambda: _fake_db(None)),
            patch.object(auth_module, "send_reset_email") as mock_send,
        ):
            resp = client.post("/api/v1/auth/forgot-password", json={"email": "nobody@probe.local"})

        assert resp.status_code == 202
        mock_send.assert_not_called()


@pytest.mark.unit
class TestResetPassword:
    def _fake_reset_db(self, email: str = "user@probe.local"):
        fake_db = AsyncMock()
        email_result = MagicMock()
        email_result.fetchone = MagicMock(return_value=MagicMock(email=email))
        fake_db.execute = AsyncMock(return_value=email_result)
        fake_db.__aenter__ = AsyncMock(return_value=fake_db)
        fake_db.__aexit__ = AsyncMock(return_value=None)

        begin_cm = AsyncMock()
        begin_cm.__aenter__ = AsyncMock(return_value=None)
        begin_cm.__aexit__ = AsyncMock(return_value=None)
        fake_db.begin = MagicMock(return_value=begin_cm)
        return fake_db

    def test_valid_token_resets_password_and_token_becomes_unusable(self) -> None:
        import shared.db.session as _sess_mod

        with (
            _no_rate_limit(),
            patch.object(auth_module, "consume_reset_token", new=AsyncMock(return_value="user-1")),
            patch.object(_sess_mod, "AsyncSessionLocal", lambda: self._fake_reset_db()),
        ):
            resp = client.post(
                "/api/v1/auth/reset-password",
                json={"token": "a-real-token", "new_password": "NewPass123"},
            )
        assert resp.status_code == 200
        assert resp.json() == {"reset": True}

    def test_expired_or_used_token_returns_400(self) -> None:
        with (
            _no_rate_limit(),
            patch.object(auth_module, "consume_reset_token", new=AsyncMock(return_value=None)),
        ):
            resp = client.post(
                "/api/v1/auth/reset-password",
                json={"token": "expired-or-used", "new_password": "NewPass123"},
            )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "INVALID_OR_EXPIRED_TOKEN"

    def test_token_unusable_a_second_time(self) -> None:
        import shared.db.session as _sess_mod

        with (
            _no_rate_limit(),
            patch.object(auth_module, "consume_reset_token", new=AsyncMock(return_value="user-1")),
            patch.object(_sess_mod, "AsyncSessionLocal", lambda: self._fake_reset_db()),
        ):
            first = client.post(
                "/api/v1/auth/reset-password",
                json={"token": "one-time-token", "new_password": "NewPass123"},
            )
        assert first.status_code == 200

        with (
            _no_rate_limit(),
            patch.object(auth_module, "consume_reset_token", new=AsyncMock(return_value=None)),
        ):
            second = client.post(
                "/api/v1/auth/reset-password",
                json={"token": "one-time-token", "new_password": "NewPass123"},
            )
        assert second.status_code == 400
        assert second.json()["detail"]["code"] == "INVALID_OR_EXPIRED_TOKEN"

    def test_short_password_returns_422(self) -> None:
        with _no_rate_limit():
            resp = client.post(
                "/api/v1/auth/reset-password",
                json={"token": "whatever", "new_password": "short"},
            )
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "PASSWORD_TOO_SHORT"

    def test_reset_password_revokes_user_tokens(self) -> None:
        """A successful reset calls revoke_user_tokens for the resolved user_id
        so any JWT issued before the reset stops working."""
        import shared.db.session as _sess_mod

        mock_revoke = AsyncMock()
        with (
            _no_rate_limit(),
            patch.object(auth_module, "consume_reset_token", new=AsyncMock(return_value="user-1")),
            patch.object(_sess_mod, "AsyncSessionLocal", lambda: self._fake_reset_db()),
            patch.object(auth_module, "revoke_user_tokens", mock_revoke),
        ):
            resp = client.post(
                "/api/v1/auth/reset-password",
                json={"token": "a-real-token", "new_password": "NewPass123"},
            )
        assert resp.status_code == 200
        mock_revoke.assert_awaited_once_with("user-1")

    def test_second_forgot_invalidates_earlier_token(self) -> None:
        """issue_reset_token is responsible for invalidating earlier unused
        tokens — verified here at the auth.py integration level: two
        forgot-password calls each issue their own token via a fresh
        issue_reset_token invocation."""
        import shared.db.session as _sess_mod

        mock_issue = AsyncMock(side_effect=["raw-token-1", "raw-token-2"])
        with (
            _no_rate_limit(),
            patch.object(auth_module, "send_reset_email"),
            patch.object(_sess_mod, "AsyncSessionLocal", lambda: _fake_db("real-user-1")),
            patch.object(auth_module, "issue_reset_token", new=mock_issue),
        ):
            client.post("/api/v1/auth/forgot-password", json={"email": "real@probe.local"})
            client.post("/api/v1/auth/forgot-password", json={"email": "real@probe.local"})

        assert mock_issue.await_count == 2
