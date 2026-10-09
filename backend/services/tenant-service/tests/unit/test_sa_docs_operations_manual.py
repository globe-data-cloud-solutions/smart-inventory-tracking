"""Unit tests: GET /sa/docs/operations-manual (sa:docs_view, platform_only).

SA gets 200 with the manual body; TA gets 403 (explicit SA-only guard,
same pattern as sa_tenant_registry); no user (no token) gets 401 from
require_permission itself. Also guards drift between docs/SA_OPERATIONS_MANUAL.md
(source of truth) and the backend static copy served by this route.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("DATABASE_URL",      "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("DATABASE_READ_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("JWT_SECRET",        "test-secret")
os.environ.setdefault("JWT_SECRET_KEY",    "test-secret")
os.environ.setdefault("ENVIRONMENT",       "local")

_TENANT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _TENANT_ROOT not in sys.path:
    sys.path.insert(0, _TENANT_ROOT)

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

_GRANT_ALL = patch(
    "shared.permissions.middleware.check_permission",
    new=AsyncMock(return_value=MagicMock(allowed=True, condition=None)),
)


def _user(role: str):
    from dependencies import UserContext
    return UserContext(user_id="u1", role=role, tenant_id=None, warehouse_id=None)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sa_gets_manual_body() -> None:
    from routers.tenants import sa_docs_operations_manual

    with _GRANT_ALL:
        response = await sa_docs_operations_manual(user=_user("SA"), db=AsyncMock())

    assert response.status_code == 200
    assert response.media_type == "text/markdown; charset=utf-8"
    assert response.headers["cache-control"] == "no-store"
    assert response.body.decode("utf-8").startswith("# SMART Platform — SA Operations Manual")


@pytest.mark.asyncio
async def test_ta_forbidden() -> None:
    from routers.tenants import sa_docs_operations_manual

    with _GRANT_ALL:
        with pytest.raises(HTTPException) as exc_info:
            await sa_docs_operations_manual(user=_user("TA"), db=AsyncMock())

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_no_token_unauthenticated() -> None:
    """require_permission raises 401 itself when user is None, before the
    handler body (and its explicit SA guard) ever runs."""
    from routers.tenants import sa_docs_operations_manual

    with pytest.raises(HTTPException) as exc_info:
        await sa_docs_operations_manual(user=None, db=AsyncMock())

    assert exc_info.value.status_code == 401


@pytest.mark.unit
def test_manual_copy_matches_source_of_truth() -> None:
    repo_root = Path(_TENANT_ROOT).resolve().parent.parent.parent
    source = repo_root / "docs" / "SA_OPERATIONS_MANUAL.md"
    if not source.exists():
        pytest.skip("docs/SA_OPERATIONS_MANUAL.md not present in this checkout")

    copy = Path(_TENANT_ROOT) / "static" / "sa_operations_manual.md"
    assert copy.read_bytes() == source.read_bytes(), (
        "backend/services/tenant-service/static/sa_operations_manual.md has drifted "
        "from docs/SA_OPERATIONS_MANUAL.md — re-run scripts/sync_help_docs.sh"
    )
