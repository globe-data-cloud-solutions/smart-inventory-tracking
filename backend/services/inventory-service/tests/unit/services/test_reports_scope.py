"""Reports (2026-10-22): scope clause and router wiring.

The SQL itself is exercised against a real database during the local check;
these unit tests cover the clause builder and that each route resolves the
caller's node scope and passes it on.
"""

from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from services import report_queries as rq

TENANT = uuid.UUID("10000000-0000-0000-0000-000000000001")
NODE = "20000000-0000-0000-0000-00000000000a"


def test_scope_clause_tenant_wide_has_no_filter() -> None:
    assert rq._scope_clause("b.warehouse_id", None) == ("", {})


def test_scope_clause_empty_set_binds_empty_array() -> None:
    clause, params = rq._scope_clause("b.warehouse_id", set())
    assert "CAST(:scope_ids AS uuid[])" in clause
    assert params == {"scope_ids": []}


def test_scope_clause_set_binds_strings() -> None:
    clause, params = rq._scope_clause("it.warehouse_id", {NODE})
    assert clause == "AND it.warehouse_id = ANY(CAST(:scope_ids AS uuid[]))"
    assert params == {"scope_ids": [NODE]}


def _user(role: str, node: str | None = NODE):
    return SimpleNamespace(role=role, tenant_id=str(TENANT), warehouse_id=node)


def _db() -> MagicMock:
    db = MagicMock()
    db.execute = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_valuation_route_passes_resolved_scope() -> None:
    from routers import reports

    scope = {NODE}
    with (
        patch.object(reports, "resolve_node_scope", new=AsyncMock(return_value=scope)),
        patch.object(reports, "get_inventory_valuation", new=AsyncMock(return_value=[])) as q,
    ):
        await reports.inventory_valuation.__wrapped__(user=_user("RM"), db=_db())
    assert q.await_args.args[2] == scope


@pytest.mark.asyncio
async def test_movement_route_parses_dates() -> None:
    from routers import reports

    with (
        patch.object(reports, "resolve_node_scope", new=AsyncMock(return_value=None)),
        patch.object(reports, "get_stock_movement", new=AsyncMock(return_value=[])) as q,
    ):
        await reports.stock_movement.__wrapped__(
            date_from="2026-01-02", date_to="2026-02-03", user=_user("TA"), db=_db()
        )
    assert q.await_args.kwargs["date_from"] == date(2026, 1, 2)
    assert q.await_args.kwargs["date_to"] == date(2026, 2, 3)


@pytest.mark.asyncio
async def test_movement_route_rejects_bad_date() -> None:
    from routers import reports

    with pytest.raises(HTTPException) as exc:
        await reports.stock_movement.__wrapped__(
            date_from="02/01/2026", date_to=None, user=_user("TA"), db=_db()
        )
    assert exc.value.status_code == 422
    assert exc.value.detail == {"code": "INVALID_DATE", "field": "date_from"}


@pytest.mark.asyncio
async def test_expiry_route_passes_window_and_scope() -> None:
    from routers import reports

    scope: set[str] = set()
    with (
        patch.object(reports, "resolve_node_scope", new=AsyncMock(return_value=scope)),
        patch.object(reports, "get_expiry_alerts", new=AsyncMock(return_value=[])) as q,
    ):
        await reports.expiry_alerts.__wrapped__(window_days=45, user=_user("WM"), db=_db())
    assert q.await_args.args[2] == scope
    assert q.await_args.kwargs["window_days"] == 45
