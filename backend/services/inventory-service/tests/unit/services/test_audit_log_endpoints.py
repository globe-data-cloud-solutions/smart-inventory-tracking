"""Regression tests for GET /api/v1/audit-log/.

Covers:
1. The include_views=false (default) bind-parameter bug fixed in e22b6ab —
   NOT LIKE '%:view' / '%:list' literals were misparsed by SQLAlchemy's
   text() as bind parameters named "view" and "list", which were never
   supplied, causing every default-mode request to fail with
   InvalidRequestError: A value is required for bind parameter 'view'.

   That filter was replaced by category-based filtering (include_system),
   but the same bind-param-safety principle applies — verified here via
   construct_params() against the compiled statement.

2. The include_system param: default false hides SYSTEM-category actions
   (anything outside transfer:*, inventory:*, adjustment:*) to align with
   the Category column grouping used by the ALL/TRANSFER/INVENTORY/
   ADJUSTMENT tabs.
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


async def _get_audit_log(client: AsyncClient, query: str):
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
            return await client.get(f"/api/v1/audit-log/{query}")
    finally:
        app.dependency_overrides.pop(get_db_session, None)


@pytest.mark.unit
class TestAuditLogIncludeSystemBindParams:

    async def test_default_excludes_system_category_without_error(
        self, client: AsyncClient
    ) -> None:
        """include_system unset (defaults to false) must not raise a
        bind-parameter error — the category LIKE patterns must be bound params."""
        resp = await _get_audit_log(client, "?page=1&limit=10")

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"] == []

    async def test_include_system_true_returns_all_categories(
        self, client: AsyncClient
    ) -> None:
        """include_system=true must also succeed (no category filter added)."""
        resp = await _get_audit_log(client, "?page=1&limit=10&include_system=true")

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"] == []
