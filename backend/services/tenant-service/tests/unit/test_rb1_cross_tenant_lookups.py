"""Regression tests for RB-1 sweep HOLEs 4-5 (docs/reviews/2026-10-19-rb1-sweep.md):
positions.py's reports_to_position_id title lookup and hierarchy.py's
_get_manager_info() both resolved a request-body id without checking it
belonged to the caller's tenant, leaking another tenant's position
title / user full name into the response. Fixed on fix/rb1-holes by adding
tenant_id to both lookups.
"""
from __future__ import annotations

import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL",      "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("DATABASE_READ_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("JWT_SECRET",        "test-secret")
os.environ.setdefault("JWT_SECRET_KEY",    "test-secret")
os.environ.setdefault("ENVIRONMENT",       "local")

_TENANT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _TENANT_ROOT not in sys.path:
    sys.path.insert(0, _TENANT_ROOT)

from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402 - sys.path/env setup above must run first

import pytest  # noqa: E402 - sys.path/env setup above must run first

pytestmark = pytest.mark.asyncio

TENANT_A = "aaaaaaaa-0000-0000-0000-000000000001"
OTHER_POSITION_ID = "cccccccc-0000-0000-0000-000000000003"
OTHER_USER_ID = "dddddddd-0000-0000-0000-000000000004"

_GRANT_ALL = patch(
    "shared.permissions.middleware.check_permission",
    new=AsyncMock(return_value=MagicMock(allowed=True, condition=None)),
)


class TestPositionsReportsToLeak:
    """HOLE 4: reports_to_position_id's title must not resolve cross-tenant."""

    async def test_reports_to_from_another_tenant_resolves_to_none_not_leaked(self) -> None:
        import routers.positions as positions_module

        db = AsyncMock()

        async def _execute(stmt, params=None):
            sql = " ".join(str(stmt).split())
            if sql.startswith("SELECT id FROM organization_node WHERE id = :nid"):
                return MagicMock(fetchone=MagicMock(return_value=MagicMock(id=params["nid"])))
            if sql.startswith("SELECT title FROM positions WHERE id = :id AND tenant_id = :tid"):
                assert params["tid"] == TENANT_A, "lookup must be tenant-scoped"
                return MagicMock(fetchone=MagicMock(return_value=None))  # not in this tenant
            if sql.startswith("INSERT INTO positions"):
                return MagicMock()
            return MagicMock(fetchone=MagicMock(return_value=None))

        db.execute = AsyncMock(side_effect=_execute)

        body = positions_module.PositionCreate(
            title="Regional Manager",
            role_code="RM",
            reports_to_position_id=uuid.UUID(OTHER_POSITION_ID),
        )
        user = MagicMock(role="TA", tenant_id=TENANT_A)

        with _GRANT_ALL:
            resp = await positions_module.create_position(
                tenant_id=uuid.UUID(TENANT_A), node_id=uuid.uuid4(), body=body, user=user, db=db,
            )
        # The cross-tenant position doesn't resolve within this tenant's scope,
        # so no title is disclosed — it must NOT silently show the other tenant's data.
        assert resp.data.reports_to_title is None


class TestManagerInfoLeak:
    """HOLE 5: manager_user_id's full_name must not resolve cross-tenant."""

    async def test_manager_from_another_tenant_is_not_resolved(self) -> None:
        from routers.hierarchy import _get_manager_info

        db = AsyncMock()

        async def _execute(stmt, params=None):
            sql = " ".join(str(stmt).split())
            assert "tenant_id = :tid" in sql, "manager lookup must be tenant-scoped"
            assert params["tid"] == TENANT_A
            return MagicMock(fetchone=MagicMock(return_value=None))  # belongs to a different tenant

        db.execute = AsyncMock(side_effect=_execute)

        name, role = await _get_manager_info(db, OTHER_USER_ID, TENANT_A)
        assert name is None and role is None

    async def test_manager_from_same_tenant_is_resolved(self) -> None:
        from routers.hierarchy import _get_manager_info

        db = AsyncMock()
        row = MagicMock()
        row.__getitem__ = lambda self, i: "Jane Manager"
        db.execute = AsyncMock(return_value=MagicMock(fetchone=MagicMock(return_value=row)))

        name, _ = await _get_manager_info(db, OTHER_USER_ID, TENANT_A)
        assert name == "Jane Manager"
