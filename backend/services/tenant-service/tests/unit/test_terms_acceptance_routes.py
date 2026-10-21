"""Unit tests for the S12 terms-acceptance routes:
GET /me/terms-acceptance (TA, tenant:view) and
GET /{tenant_id}/terms-acceptance (SA, tenant:manage + inline SA check).

terms_acceptances is written only by public_signup.py (CLAUDE.md §15 S4) —
an SA-created tenant never gets a row, which these routes must report as
nulls rather than an error.

Mocked session + mocked permission store throughout — no real DB
connection required.
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL",      "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("DATABASE_READ_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("JWT_SECRET",        "test-secret")
os.environ.setdefault("JWT_SECRET_KEY",    "test-secret")
os.environ.setdefault("ENVIRONMENT",       "local")
os.environ.setdefault("TERMS_VERSION",     "2026-10")

_TENANT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _TENANT_ROOT not in sys.path:
    sys.path.insert(0, _TENANT_ROOT)

from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402 - sys.path/env setup above must run first

import pytest  # noqa: E402 - sys.path/env setup above must run first
from fastapi import HTTPException  # noqa: E402 - sys.path/env setup above must run first

pytestmark = pytest.mark.asyncio

TENANT_A = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")


def _user(role: str, tenant_id: str | None):
    from dependencies import UserContext
    return UserContext(user_id="u-1", role=role, tenant_id=tenant_id, warehouse_id=None)


def _full_grant():
    grant = MagicMock()
    grant.grant_type = "FULL"
    return grant


def _row(terms_version: str, accepted_at: datetime, email: str):
    r = MagicMock()
    r.terms_version = terms_version
    r.accepted_at = accepted_at
    r.email = email
    return r


def _db_with_row(row) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.fetchone.return_value = row
    db.execute.return_value = result
    return db


async def test_ta_terms_acceptance_found() -> None:
    from routers.tenants import get_my_terms_acceptance

    ta = _user("TA", str(TENANT_A))
    accepted_at = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    db = _db_with_row(_row("2026-05", accepted_at, "ta@acme.com"))
    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()):
        out = await get_my_terms_acceptance(user=ta, db=db)

    assert out.data.accepted_version == "2026-05"
    assert out.data.accepted_by_email == "ta@acme.com"
    assert out.data.current_version == "2026-10"
    assert out.data.accepted_at == accepted_at.isoformat()


async def test_ta_terms_acceptance_no_row_returns_nulls() -> None:
    """SA-created tenants never get a terms_acceptances row — not an error."""
    from routers.tenants import get_my_terms_acceptance

    ta = _user("TA", str(TENANT_A))
    db = _db_with_row(None)
    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()):
        out = await get_my_terms_acceptance(user=ta, db=db)

    assert out.data.accepted_version is None
    assert out.data.accepted_at is None
    assert out.data.accepted_by_email is None
    assert out.data.current_version == "2026-10"


async def test_sa_terms_acceptance_for_any_tenant() -> None:
    from routers.tenants import get_tenant_terms_acceptance

    sa = _user("SA", None)
    accepted_at = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    db = _db_with_row(_row("2026-05", accepted_at, "ta@acme.com"))
    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()):
        out = await get_tenant_terms_acceptance(tenant_id=TENANT_A, user=sa, db=db)

    assert out.data.accepted_version == "2026-05"
    assert out.data.current_version == "2026-10"


async def test_sa_terms_acceptance_denied_for_non_sa() -> None:
    """TENANT_MANAGE RBAC passes, but the inline SA-only check must still
    reject a non-SA caller (same pattern as GET /{tenant_id}/plan)."""
    from routers.tenants import get_tenant_terms_acceptance

    ta = _user("TA", str(TENANT_A))
    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc_info:
            await get_tenant_terms_acceptance(tenant_id=TENANT_A, user=ta, db=AsyncMock())

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "FORBIDDEN"
