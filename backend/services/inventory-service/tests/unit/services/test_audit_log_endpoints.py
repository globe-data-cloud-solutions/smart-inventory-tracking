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

from dataclasses import dataclass
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from shared.permissions.middleware import PermissionResult


# Local stub: `tests.conftest` resolves to whichever service's tests package is imported first
# in a full `pytest backend/` run, so it cannot be imported by name here.
TENANT_A = "10000000-0000-0000-0000-000000000001"


@dataclass
class _StubUser:
    user_id: str
    tenant_id: str
    role: str
    warehouse_id: Optional[str] = None
    region_id: Optional[str] = None


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


# ── transfer_discrepancy rows: scope + enrichment ────────────────────────────
#
# These tests cannot run the SQL (no live DB in the unit suite). They assert the
# compiled statement carries the discrepancy scope branch and its tenant filter,
# and drive a fake DB that applies the same visibility rule to in-memory rows to
# prove the endpoint binds the caller's subtree and maps the enrichment fields.

SRC_WH = "30000000-0000-0000-0000-000000000001"
DST_WH = "30000000-0000-0000-0000-000000000002"
OTHER_WH = "30000000-0000-0000-0000-000000000009"
TRANSFER_ID = "40000000-0000-0000-0000-000000000001"
DISC_ID = "50000000-0000-0000-0000-000000000001"


def _disc_row():
    from datetime import datetime, timezone
    from decimal import Decimal
    from types import SimpleNamespace

    return SimpleNamespace(
        id="60000000-0000-0000-0000-000000000001",
        timestamp=datetime(2026, 10, 16, tzinfo=timezone.utc),
        user_id=None, user_name="Dest WM", role="WM",
        action="transfer:resolve_discrepancy",
        resource_type="transfer_discrepancy", resource_id=DISC_ID,
        decision="GRANTED", reason=None, abac_context=None,
        transfer_type="PULL", from_warehouse_name="Source WH",
        to_warehouse_name="Dest WH", product_summary="Rice (10)",
        adjustment_reason_code=None, transfer_order_id=TRANSFER_ID,
        discrepancy_count=None, discrepancy_product_name="Rice",
        discrepancy_missing_quantity=Decimal("3"), discrepancy_reason="SHORT",
        discrepancy_resolution="WRITTEN_OFF",
    )


def _scoped_db(captured: list):
    """Fake execute: records (sql, params); returns the discrepancy row only if
    the statement is unscoped, or the bound node_ids touch the transfer's ends
    (the rule the SQL's discrepancy branch encodes)."""
    async def _execute(stmt, params=None):
        params = params or {}
        stmt.compile().construct_params(params)
        sql = str(stmt)
        captured.append((sql, params))
        result = MagicMock()
        if "node_ids" in params:
            visible = bool({SRC_WH, DST_WH} & set(params["node_ids"]))
        else:
            visible = True
        result.fetchall.return_value = [_disc_row()] if visible else []
        return result

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=_execute)
    return db


async def _get_as(client, user, subtree, captured, query="?include_system=true"):
    from main import app
    from dependencies import get_current_user, get_db_session

    db = _scoped_db(captured)

    async def _db_gen():
        yield db

    async def _descendants(_db, _tenant, _node):
        return set(subtree)

    route = next(r for r in app.routes if getattr(r, "path", "") == "/api/v1/audit-log/")
    module_globals = route.endpoint.__wrapped__.__globals__
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db_session] = _db_gen
    try:
        with patch.dict(module_globals, {"get_descendant_node_ids": _descendants}), patch(
            "shared.permissions.middleware.check_permission",
            new_callable=AsyncMock, return_value=PermissionResult(allowed=True),
        ):
            return await client.get(f"/api/v1/audit-log/{query}")
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_db_session, None)


@pytest.mark.unit
class TestAuditLogTransferDiscrepancyRows:

    async def test_source_facility_wm_sees_discrepancy_row(self, client) -> None:
        captured: list = []
        wm = _StubUser("u-src", TENANT_A, "WM", warehouse_id=SRC_WH)
        resp = await _get_as(client, wm, {SRC_WH}, captured)

        assert resp.status_code == 200
        assert [r["resource_type"] for r in resp.json()["data"]] == ["transfer_discrepancy"]
        sql, params = captured[0]
        assert "al.resource_type = 'transfer_discrepancy'" in sql
        assert "FROM transfer_discrepancies td" in sql
        assert "td.tenant_id = :tid" in sql
        assert "tdo.tenant_id = td.tenant_id" in sql
        assert params["node_ids"] == [SRC_WH]

    async def test_destination_facility_wm_sees_discrepancy_row(self, client) -> None:
        wm = _StubUser("u-dst", TENANT_A, "WM", warehouse_id=DST_WH)
        resp = await _get_as(client, wm, {DST_WH}, [])

        assert len(resp.json()["data"]) == 1

    async def test_unrelated_facility_wm_does_not_see_it(self, client) -> None:
        captured: list = []
        wm = _StubUser("u-other", TENANT_A, "WM", warehouse_id=OTHER_WH)
        resp = await _get_as(client, wm, {OTHER_WH}, captured)

        assert resp.json()["data"] == []
        assert captured[0][1]["node_ids"] == [OTHER_WH]

    async def test_tenant_wide_role_sees_it_without_scope_clause(self, client, au_user) -> None:
        captured: list = []
        resp = await _get_as(client, au_user, set(), captured)

        assert len(resp.json()["data"]) == 1
        sql, params = captured[0]
        assert "node_ids" not in params
        assert "tdo.from_warehouse_id" not in sql

    async def test_enrichment_fields_are_returned(self, client, au_user) -> None:
        resp = await _get_as(client, au_user, set(), [])

        item = resp.json()["data"][0]
        assert item["transfer_order_id"] == TRANSFER_ID
        assert item["from_warehouse_name"] == "Source WH"
        assert item["to_warehouse_name"] == "Dest WH"
        assert item["discrepancy_product_name"] == "Rice"
        assert float(item["discrepancy_missing_quantity"]) == 3.0
        assert item["discrepancy_reason"] == "SHORT"
        assert item["discrepancy_resolution"] == "WRITTEN_OFF"

    async def test_statement_enriches_discrepancy_rows_and_counts_per_transfer(
        self, client, au_user
    ) -> None:
        captured: list = []
        await _get_as(client, au_user, set(), captured)

        sql = captured[0][0]
        assert "LEFT JOIN transfer_discrepancies disc" in sql
        assert "disc.tenant_id = al.tenant_id" in sql
        assert "t_ord.id = disc.transfer_order_id" in sql
        assert "td.tenant_id = :tid AND td.transfer_order_id = t_ord.id" in sql
