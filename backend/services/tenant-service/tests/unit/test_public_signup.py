"""Unit tests for routers.public_signup — body validation, slug collision,
duplicate email, and non-public-tier rejection.

Rate limiting (routers.public_signup.rate_limit_hit) is patched to a no-op in
every test here — it has its own unit tests in
backend/shared/cache/tests/test_rate_limit.py and must not depend on a real
Redis connection for these tests.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("DATABASE_URL",      "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("DATABASE_READ_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("JWT_SECRET",        "test-secret")
os.environ.setdefault("JWT_SECRET_KEY",    "test-secret")
os.environ.setdefault("ENVIRONMENT",       "local")
os.environ.setdefault("REDIS_URL",         "redis://localhost:6379/0")

_TENANT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _TENANT_ROOT not in sys.path:
    sys.path.insert(0, _TENANT_ROOT)

from typing import Any  # noqa: E402 - sys.path/env setup above must run first
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402 - sys.path/env setup above must run first

import pytest  # noqa: E402 - sys.path/env setup above must run first
from fastapi import HTTPException  # noqa: E402 - sys.path/env setup above must run first


def _signup_kwargs(**overrides: Any) -> dict[str, Any]:
    base = dict(
        company_name="Probe Co",
        slug="probe-co",
        organisation_type="RETAILER",
        industry=None,
        default_locale="en",
        tier="GROWTH",
        billing_period="MONTHLY",
        admin_full_name="Probe Admin",
        admin_email="probe-admin@example.com",
        admin_password="TestPass123",
        phone=None,
        accept_terms=True,
        terms_version="2026-10",
    )
    base.update(overrides)
    return base


def _fake_request(ip: str = "1.2.3.4") -> MagicMock:
    request = MagicMock()
    request.headers = {"User-Agent": "pytest"}
    request.client.host = ip
    return request


def _make_db(execute_side_effect) -> MagicMock:
    """A fake AsyncSessionLocal() instance supporting both
    `async with AsyncSessionLocal() as db:` and `async with db.begin():`."""
    fake_db = AsyncMock()
    fake_db.execute = AsyncMock(side_effect=execute_side_effect)
    fake_db.__aenter__ = AsyncMock(return_value=fake_db)
    fake_db.__aexit__ = AsyncMock(return_value=None)

    begin_cm = AsyncMock()
    begin_cm.__aenter__ = AsyncMock(return_value=None)
    begin_cm.__aexit__ = AsyncMock(return_value=None)
    fake_db.begin = MagicMock(return_value=begin_cm)
    return fake_db


def _package_row(tier: str = "GROWTH", is_public: bool = True) -> MagicMock:
    row = MagicMock()
    row.tier = tier
    row.display_name = tier.capitalize()
    row.max_warehouses = 10
    row.max_users = 25
    row.sku_cap = 1500
    row.feature_flags = {"CORE_INVENTORY": True}
    row.is_public = is_public
    row.sort_order = 2
    return row


pytestmark = pytest.mark.asyncio


async def _call_signup(body_kwargs: dict[str, Any], execute_side_effect, ip: str = "1.2.3.4"):
    from routers.public_signup import SignupRequest, public_signup

    fake_db = _make_db(execute_side_effect)
    body = SignupRequest(**body_kwargs)

    with patch("routers.public_signup.rate_limit_hit", new=AsyncMock(return_value=None)), \
         patch("routers.public_signup.AsyncSessionLocal", lambda: fake_db):
        return await public_signup(body=body, request=_fake_request(ip))


# ── Body validation (no DB call reached) ─────────────────────────────────────

async def test_invalid_organisation_type_returns_422() -> None:
    async def _execute(sql, params=None, **kw):
        raise AssertionError("must not reach the DB")

    with pytest.raises(HTTPException) as exc_info:
        await _call_signup(_signup_kwargs(organisation_type="BOGUS"), _execute)
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "INVALID_ORGANISATION_TYPE"


async def test_invalid_billing_period_returns_422() -> None:
    async def _execute(sql, params=None, **kw):
        raise AssertionError("must not reach the DB")

    with pytest.raises(HTTPException) as exc_info:
        await _call_signup(_signup_kwargs(billing_period="WEEKLY"), _execute)
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "INVALID_BILLING_PERIOD"


async def test_terms_not_accepted_returns_422() -> None:
    async def _execute(sql, params=None, **kw):
        raise AssertionError("must not reach the DB")

    with pytest.raises(HTTPException) as exc_info:
        await _call_signup(_signup_kwargs(accept_terms=False), _execute)
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "TERMS_NOT_ACCEPTED"


async def test_terms_version_mismatch_returns_422() -> None:
    async def _execute(sql, params=None, **kw):
        raise AssertionError("must not reach the DB")

    with pytest.raises(HTTPException) as exc_info:
        await _call_signup(_signup_kwargs(terms_version="2020-01"), _execute)
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "TERMS_VERSION_MISMATCH"


async def test_terms_version_mismatch_after_runtime_env_change(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_terms_version() reads TERMS_VERSION at call time, not at import
    time — a request sent with the version that was current a moment ago
    must be rejected once the env var changes underneath the running
    process (service restarted with a new TERMS_VERSION on the command
    line, no code change)."""
    monkeypatch.setenv("TERMS_VERSION", "2026-11")

    async def _execute(sql, params=None, **kw):
        raise AssertionError("must not reach the DB")

    with pytest.raises(HTTPException) as exc_info:
        await _call_signup(_signup_kwargs(terms_version="2026-10"), _execute)
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "TERMS_VERSION_MISMATCH"
    assert exc_info.value.detail["message"] == "The current terms version is 2026-11."


# ── DB-backed validation ──────────────────────────────────────────────────────

async def test_non_public_tier_returns_422_invalid_tier() -> None:
    async def _execute(sql, params=None, **kw):
        if "set_config" in str(sql):
            return MagicMock()
        if "platform_tier_config" in str(sql):
            res = MagicMock()
            res.fetchone = MagicMock(return_value=_package_row("GROWTH", is_public=False))
            return res
        raise AssertionError(f"unexpected query reached: {sql}")

    with pytest.raises(HTTPException) as exc_info:
        await _call_signup(_signup_kwargs(), _execute)
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "INVALID_TIER"


async def test_slug_already_taken_returns_409() -> None:
    async def _execute(sql, params=None, **kw):
        if "set_config" in str(sql):
            return MagicMock()
        if "platform_tier_config" in str(sql):
            res = MagicMock()
            res.fetchone = MagicMock(return_value=_package_row("GROWTH"))
            return res
        if "SELECT id FROM tenants WHERE slug" in str(sql):
            res = MagicMock()
            res.fetchone = MagicMock(return_value=MagicMock(id="existing-tenant"))
            return res
        raise AssertionError(f"unexpected query reached: {sql}")

    with pytest.raises(HTTPException) as exc_info:
        await _call_signup(_signup_kwargs(), _execute)
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "SLUG_ALREADY_EXISTS"


async def test_duplicate_email_returns_409_generic_message() -> None:
    async def _execute(sql, params=None, **kw):
        if "set_config" in str(sql):
            return MagicMock()
        if "platform_tier_config" in str(sql):
            res = MagicMock()
            res.fetchone = MagicMock(return_value=_package_row("GROWTH"))
            return res
        if "SELECT id FROM tenants WHERE slug" in str(sql):
            res = MagicMock()
            res.fetchone = MagicMock(return_value=None)
            return res
        if "SELECT id FROM users WHERE lower(email)" in str(sql):
            res = MagicMock()
            res.fetchone = MagicMock(return_value=MagicMock(id="someone-elses-user"))
            return res
        raise AssertionError(f"unexpected query reached: {sql}")

    with pytest.raises(HTTPException) as exc_info:
        await _call_signup(_signup_kwargs(), _execute)
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "DUPLICATE_EMAIL"
    # Never reveals which tenant already owns the email.
    assert "tenant" not in exc_info.value.detail["message"].lower()
