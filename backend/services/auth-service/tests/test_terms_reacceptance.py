"""Unit tests for account-owner terms re-acceptance on login
(_lookup_user_with_position's terms_acceptance_required flag).

Mirrors test_auth.py's sys.path isolation so auth-service's bare module
names (main, routers) don't leak into later-running service tests.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("DATABASE_URL",      "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("DATABASE_READ_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("JWT_SECRET",        "test-secret")
os.environ.setdefault("JWT_SECRET_KEY",    "test-secret")
os.environ.setdefault("ENVIRONMENT",       "local")
os.environ.setdefault("TERMS_VERSION",     "2026-10")

_AUTH_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_was_on_path = _AUTH_ROOT in sys.path
if not _was_on_path:
    sys.path.insert(0, _AUTH_ROOT)

import routers.auth as auth_module  # noqa: E402

for _mod in ("main", "routers", "routers.auth", "routers.__init__"):
    sys.modules.pop(_mod, None)
if not _was_on_path:
    try:
        sys.path.remove(_AUTH_ROOT)
    except ValueError:
        pass
# ─────────────────────────────────────────────────────────────────────────────

import pytest  # noqa: E402

pytestmark = pytest.mark.asyncio

TENANT_ID = "aaaaaaaa-0000-0000-0000-000000000001"


def _user_row(is_account_owner: bool) -> MagicMock:
    row = MagicMock()
    row.id                 = "u-owner-1"
    row.email               = "owner@acme.com"
    row.full_name           = "Owner Person"
    row.tenant_id           = TENANT_ID
    row.password_hash       = None
    row.must_reset_password = False
    row.system_role         = "TA"
    row.is_active           = True
    row.email_verified_at   = datetime(2026, 1, 1, tzinfo=timezone.utc)
    row.is_account_owner    = is_account_owner
    row.tenant_slug         = "acme"
    row.tenant_active       = True
    row.tenant_status       = "ACTIVE"
    return row


def _terms_row(terms_version: str) -> MagicMock:
    row = MagicMock()
    row.terms_version = terms_version
    return row


def _dispatching_db(user_row: MagicMock, terms_row: object) -> AsyncMock:
    """Fake AsyncSessionLocal() context manager whose execute() returns the
    user row for the users/tenants SELECT and the terms row (or None) for the
    terms_acceptances SELECT — dispatched by inspecting the query text, not
    call order, so this works regardless of how many queries run."""
    async def _execute(query, *args, **kwargs):
        sql = str(getattr(query, "text", query))
        result = MagicMock()
        if "terms_acceptances" in sql:
            result.fetchone = MagicMock(return_value=terms_row)
        else:
            result.fetchone = MagicMock(return_value=user_row)
        return result

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=_execute)
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__  = AsyncMock(return_value=None)
    return db


async def test_owner_with_old_terms_version_flag_true(monkeypatch: pytest.MonkeyPatch) -> None:
    import shared.db.session as _sess_mod
    db = _dispatching_db(_user_row(True), _terms_row("2026-09"))
    monkeypatch.setattr(_sess_mod, "AsyncSessionLocal", lambda: db)

    claims = await auth_module._lookup_user_with_position("owner@acme.com")
    assert claims["terms_acceptance_required"] is True


async def test_owner_with_current_terms_version_flag_false(monkeypatch: pytest.MonkeyPatch) -> None:
    import shared.db.session as _sess_mod
    db = _dispatching_db(_user_row(True), _terms_row("2026-10"))
    monkeypatch.setattr(_sess_mod, "AsyncSessionLocal", lambda: db)

    claims = await auth_module._lookup_user_with_position("owner@acme.com")
    assert claims["terms_acceptance_required"] is False


async def test_owner_with_no_terms_row_flag_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """SA-path tenants (no public_signup row ever written) must still be
    gated — no row counts as required, same as a stale version."""
    import shared.db.session as _sess_mod
    db = _dispatching_db(_user_row(True), None)
    monkeypatch.setattr(_sess_mod, "AsyncSessionLocal", lambda: db)

    claims = await auth_module._lookup_user_with_position("owner@acme.com")
    assert claims["terms_acceptance_required"] is True


async def test_non_owner_flag_false_even_with_stale_terms(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the account owner is ever gated — a non-owner TA sees false
    regardless of the tenant's terms-acceptance state."""
    import shared.db.session as _sess_mod
    db = _dispatching_db(_user_row(False), _terms_row("2026-09"))
    monkeypatch.setattr(_sess_mod, "AsyncSessionLocal", lambda: db)

    claims = await auth_module._lookup_user_with_position("owner@acme.com")
    assert claims["terms_acceptance_required"] is False
