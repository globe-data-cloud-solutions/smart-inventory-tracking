"""Regression tests for GET /api/v1/audit-log/.

Covers the include_views=false (default) bind-parameter bug: the
NOT LIKE '%:view' / '%:list' literals were misparsed by SQLAlchemy's
text() as bind parameters named "view" and "list", which were never
supplied, causing every default-mode request to fail with
InvalidRequestError: A value is required for bind parameter 'view'.

Same class of bug as the _get_warehouse_name fix in bc52540 — literal
colons in raw SQL strings must be bound as parameters, not embedded.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from shared.permissions.middleware import PermissionResult


def _fake_execute_factory():
    """Returns an async execute() that performs real SQLAlchemy bind-param
    validation on the compiled text() statement, without needing a live DB.

    construct_params() raises InvalidRequestError if the statement contains
    a bind parameter (including ones accidentally parsed out of string
    literals like '%:view') that isn't present in the supplied params dict —
    reproducing the exact failure mode of the original bug.
    """
    async def _execute(stmt, params=None):
        compiled = stmt.compile()
        compiled.construct_params(params or {})
        result = MagicMock()
        result.fetchall.return_value = []
        return result

    return AsyncMock(side_effect=_execute)


@pytest.mark.unit
class TestAuditLogIncludeViewsBindParams:

    async def test_default_excludes_view_list_actions_without_error(
        self, client: AsyncClient
    ) -> None:
        """include_views unset (defaults to false) must not raise a
        bind-parameter error — the NOT LIKE patterns must be bound params."""
        db = AsyncMock()
        db.execute = _fake_execute_factory()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()

        from main import app
        from dependencies import get_db_session

        async def _db_gen():
            yield db

        app.dependency_overrides[get_db_session] = _db_gen
        try:
            with patch(
                "shared.permissions.middleware.check_permission",
                new_callable=AsyncMock,
                return_value=PermissionResult(allowed=True),
            ):
                resp = await client.get("/api/v1/audit-log/?page=1&limit=10")
        finally:
            app.dependency_overrides.pop(get_db_session, None)

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"] == []

    async def test_include_views_true_returns_all_actions(
        self, client: AsyncClient
    ) -> None:
        """include_views=true must also succeed (no NOT LIKE clauses added)."""
        db = AsyncMock()
        db.execute = _fake_execute_factory()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()

        from main import app
        from dependencies import get_db_session

        async def _db_gen():
            yield db

        app.dependency_overrides[get_db_session] = _db_gen
        try:
            with patch(
                "shared.permissions.middleware.check_permission",
                new_callable=AsyncMock,
                return_value=PermissionResult(allowed=True),
            ):
                resp = await client.get("/api/v1/audit-log/?page=1&limit=10&include_views=true")
        finally:
            app.dependency_overrides.pop(get_db_session, None)

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"] == []
