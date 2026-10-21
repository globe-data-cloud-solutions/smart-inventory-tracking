"""Unit tests for POST /me/terms-acceptance — account-owner re-acceptance
of the current terms version (feature (b), terms re-acceptance gate).

Mocked session + mocked permission store throughout — no real DB
connection required. Each fake db dispatches its canned result by
inspecting the query text, not call order, so it is robust to any extra
query the handler adds.
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL",      "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("DATABASE_READ_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("JWT_SECRET",        "test-secret")
os.environ.setdefault("JWT_SECRET_KEY",    "test-secret")
os.environ.setdefault("ENVIRONMENT",       "local")
os.environ.setdefault("TERMS_VERSION",     "2026-10")

_TENANT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _TENANT_ROOT not in sys.path:
    sys.path.insert(0, _TENANT_ROOT)

import pytest  # noqa: E402 - sys.path/env setup above must run first
from fastapi import HTTPException  # noqa: E402 - sys.path/env setup above must run first

pytestmark = pytest.mark.asyncio

TENANT_A = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")


def _user(role: str, tenant_id: str | None, user_id: str = "u-owner-1"):
    from dependencies import UserContext
    return UserContext(user_id=user_id, role=role, tenant_id=tenant_id, warehouse_id=None)


def _full_grant():
    grant = MagicMock()
    grant.grant_type = "FULL"
    return grant


class _FakeRequest:
    def __init__(self) -> None:
        self.headers = {"User-Agent": "pytest-agent"}
        self.client = None


def _make_db(is_account_owner: bool, latest_terms_version: str | None):
    """Dispatches by SQL text:
      - users.is_account_owner lookup
      - terms_acceptances JOIN users (GET-style read)
      - INSERT INTO terms_acceptances
      - tenant_activity_log actor_email lookup / insert
    Tracks every INSERT statement issued so a test can assert no duplicate
    terms_acceptances row is written on a repeated call.
    """
    inserts: list[str] = []
    accepted_at = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)

    def _current_terms_row():
        if latest_terms_version is None:
            return None
        row = MagicMock()
        row.terms_version = latest_terms_version
        row.accepted_at = accepted_at
        row.email = "owner@acme.com"
        return row

    async def _execute(query, params=None, *args, **kwargs):
        sql = str(getattr(query, "text", query))
        result = MagicMock()
        if "is_account_owner FROM users" in sql:
            row = MagicMock()
            row.is_account_owner = is_account_owner
            result.fetchone = MagicMock(return_value=row)
        elif "FROM terms_acceptances ta JOIN users u" in sql:
            result.fetchone = MagicMock(return_value=_current_terms_row())
        elif "INSERT INTO terms_acceptances" in sql:
            inserts.append(sql)
        elif "SELECT email FROM users WHERE id" in sql:
            row = MagicMock()
            row.email = "owner@acme.com"
            result.fetchone = MagicMock(return_value=row)
        elif "INSERT INTO tenant_activity_log" in sql:
            pass
        return result

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=_execute)
    return db, inserts


async def test_post_by_non_owner_returns_403() -> None:
    from routers.tenants import accept_current_terms

    ta = _user("TA", str(TENANT_A))
    db, inserts = _make_db(is_account_owner=False, latest_terms_version="2026-09")
    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc_info:
            await accept_current_terms(request=_FakeRequest(), user=ta, db=db)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "NOT_ACCOUNT_OWNER"
    assert inserts == []


async def test_post_inserts_with_current_version() -> None:
    from routers.tenants import accept_current_terms

    owner = _user("TA", str(TENANT_A))
    db, inserts = _make_db(is_account_owner=True, latest_terms_version="2026-09")
    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()):
        out = await accept_current_terms(request=_FakeRequest(), user=owner, db=db)

    assert len(inserts) == 1
    assert out.data.current_version == "2026-10"


async def test_post_repeated_does_not_duplicate_insert() -> None:
    """Idempotent: latest acceptance already equals the current version, so
    no new row is written — the handler returns the existing one."""
    from routers.tenants import accept_current_terms

    owner = _user("TA", str(TENANT_A))
    db, inserts = _make_db(is_account_owner=True, latest_terms_version="2026-10")
    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()):
        out = await accept_current_terms(request=_FakeRequest(), user=owner, db=db)

    assert inserts == []
    assert out.data.accepted_version == "2026-10"
    assert out.data.current_version == "2026-10"
