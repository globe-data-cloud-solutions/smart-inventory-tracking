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


def _req(tenant_id: str | None = None) -> SimpleNamespace:
    """Just enough of a Request for _rls_tenant_for: the query string."""
    return SimpleNamespace(query_params={"tenant_id": tenant_id} if tenant_id else {})


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
        await reports.inventory_valuation.__wrapped__(
            level=None, node_id=None, warehouse_id=None, request=_req(), user=_user("RM"), db=_db()
        )
    assert q.await_args.args[2] == scope


@pytest.mark.asyncio
async def test_movement_route_parses_dates() -> None:
    from routers import reports

    with (
        patch.object(reports, "resolve_node_scope", new=AsyncMock(return_value=None)),
        patch.object(reports, "get_stock_movement", new=AsyncMock(return_value=[])) as q,
    ):
        await reports.stock_movement.__wrapped__(
            date_from="2026-01-02",
            date_to="2026-02-03",
            level=None,
            node_id=None,
            warehouse_id=None,
            request=_req(),
            user=_user("TA"),
            db=_db(),
        )
    assert q.await_args.kwargs["date_from"] == date(2026, 1, 2)
    assert q.await_args.kwargs["date_to"] == date(2026, 2, 3)


@pytest.mark.asyncio
async def test_movement_route_rejects_bad_date() -> None:
    from routers import reports

    with pytest.raises(HTTPException) as exc:
        await reports.stock_movement.__wrapped__(
            date_from="02/01/2026",
            date_to=None,
            level=None,
            node_id=None,
            warehouse_id=None,
            request=_req(),
            user=_user("TA"),
            db=_db(),
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
        await reports.expiry_alerts.__wrapped__(
            window_days=45,
            level=None,
            node_id=None,
            warehouse_id=None,
            request=_req(),
            user=_user("WM"),
            db=_db(),
        )
    assert q.await_args.args[2] == scope
    assert q.await_args.kwargs["window_days"] == 45


# ── Filters by level, node and warehouse (2026-10-22) ───────────────────────

from services import report_filters as rf  # noqa: E402

NODE_B = "20000000-0000-0000-0000-00000000000b"
NODE_C = "20000000-0000-0000-0000-00000000000c"
WH_1 = "30000000-0000-0000-0000-000000000001"


def test_intersect_scopes_only_narrows() -> None:
    assert rf.intersect_scopes(None, None) is None
    assert rf.intersect_scopes(None, {NODE}) == {NODE}
    assert rf.intersect_scopes({NODE}, None) == {NODE}
    assert rf.intersect_scopes({NODE, NODE_B}, {NODE_B, NODE_C}) == {NODE_B}
    assert rf.intersect_scopes(set(), {NODE}) == set()


def _level_db(at_level: bool = True) -> MagicMock:
    db = MagicMock()
    row = MagicMock() if at_level else None
    result = MagicMock()
    result.first.return_value = row
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.asyncio
async def test_filter_scope_none_when_no_filter_given() -> None:
    db = _level_db()
    assert await rf.filter_scope(db, str(TENANT), None, None, None) is None
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_filter_scope_node_selects_its_subtree_lowercased() -> None:
    with patch.object(
        rf,
        "get_descendant_node_ids",
        new=AsyncMock(return_value={NODE.upper(), NODE_C.upper()}),
    ):
        out = await rf.filter_scope(_level_db(), str(TENANT), None, NODE, None)
    assert out == {NODE, NODE_C}


@pytest.mark.asyncio
async def test_filter_scope_level_requires_node() -> None:
    with pytest.raises(HTTPException) as exc:
        await rf.filter_scope(_level_db(), str(TENANT), 2, None, None)
    assert exc.value.detail == {"code": "INVALID_FILTER", "field": "level"}


@pytest.mark.asyncio
async def test_filter_scope_rejects_node_not_at_level() -> None:
    with pytest.raises(HTTPException) as exc:
        await rf.filter_scope(_level_db(at_level=False), str(TENANT), 2, NODE, None)
    assert exc.value.detail == {"code": "INVALID_FILTER", "field": "node_id"}


@pytest.mark.asyncio
async def test_filter_scope_rejects_malformed_uuid() -> None:
    with pytest.raises(HTTPException) as exc:
        await rf.filter_scope(_level_db(), str(TENANT), None, "not-a-uuid", None)
    assert exc.value.detail == {"code": "INVALID_FILTER", "field": "node_id"}


@pytest.mark.asyncio
async def test_filter_scope_warehouse_and_node_intersect() -> None:
    with patch.object(rf, "get_descendant_node_ids", new=AsyncMock(return_value={NODE, NODE_B})):
        out = await rf.filter_scope(_level_db(), str(TENANT), None, NODE, WH_1)
    assert out == set()


@pytest.mark.asyncio
async def test_route_narrows_caller_scope_by_filter() -> None:
    """A RM whose region is {NODE, NODE_B} filters to NODE_B and gets only that."""
    from routers import reports

    caller = {NODE, NODE_B}
    chosen = {NODE_B, NODE_C}
    with (
        patch.object(reports, "resolve_node_scope", new=AsyncMock(return_value=caller)),
        patch.object(reports, "filter_scope", new=AsyncMock(return_value=chosen)),
        patch.object(reports, "get_inventory_valuation", new=AsyncMock(return_value=[])) as q,
    ):
        await reports.inventory_valuation.__wrapped__(
            level=None,
            node_id=NODE_B,
            warehouse_id=None,
            request=_req(),
            user=_user("RM"),
            db=_db(),
        )
    assert q.await_args.args[2] == {NODE_B}


@pytest.mark.asyncio
async def test_route_filter_cannot_widen_a_scoped_caller() -> None:
    from routers import reports

    with (
        patch.object(reports, "resolve_node_scope", new=AsyncMock(return_value={NODE})),
        patch.object(reports, "filter_scope", new=AsyncMock(return_value={NODE_C})),
        patch.object(reports, "get_expiry_alerts", new=AsyncMock(return_value=[])) as q,
    ):
        await reports.expiry_alerts.__wrapped__(
            window_days=30,
            level=None,
            node_id=NODE_C,
            warehouse_id=None,
            request=_req(),
            user=_user("WM"),
            db=_db(),
        )
    assert q.await_args.args[2] == set()


@pytest.mark.asyncio
async def test_filter_options_returns_levels_and_only_in_scope_nodes() -> None:
    from routers import reports

    levels = [
        SimpleNamespace(level_number=1, level_name="National"),
        SimpleNamespace(level_number=2, level_name="Region"),
    ]
    nodes = [
        SimpleNamespace(
            id=uuid.UUID(NODE), name="North", code="N", hierarchy_level=2, parent_node_id=None
        ),
        SimpleNamespace(
            id=uuid.UUID(NODE_C),
            name="Depot",
            code="D",
            hierarchy_level=3,
            parent_node_id=uuid.UUID(NODE),
        ),
        SimpleNamespace(
            id=uuid.UUID(NODE_B), name="South", code="S", hierarchy_level=2, parent_node_id=None
        ),
    ]
    db = MagicMock()
    lvl_result, node_result = MagicMock(), MagicMock()
    lvl_result.all.return_value = levels
    node_result.all.return_value = nodes
    db.execute = AsyncMock(side_effect=[lvl_result, node_result])

    with patch.object(reports, "resolve_node_scope", new=AsyncMock(return_value={NODE, NODE_C})):
        out = await reports.report_filter_options.__wrapped__(
            request=_req(), user=_user("RM"), db=db
        )

    assert [lv.level_name for lv in out.data.levels] == ["National", "Region"]
    assert {str(n.id) for n in out.data.nodes} == {NODE, NODE_C}


# ── Tenant resolution: SA scopes with ?tenant_id, everyone else the token ───

OTHER_TENANT = uuid.UUID("10000000-0000-0000-0000-000000000002")


def _sa() -> SimpleNamespace:
    return SimpleNamespace(role="SA", tenant_id=None, warehouse_id=None)


@pytest.mark.asyncio
async def test_sa_with_tenant_query_resolves_that_tenant_for_valuation() -> None:
    from routers import reports

    with (
        patch.object(reports, "resolve_node_scope", new=AsyncMock(return_value=None)),
        patch.object(reports, "get_inventory_valuation", new=AsyncMock(return_value=[])) as q,
    ):
        await reports.inventory_valuation.__wrapped__(
            request=_req(str(OTHER_TENANT)),
            level=None,
            node_id=None,
            warehouse_id=None,
            user=_sa(),
            db=_db(),
        )
    assert q.await_args.args[1] == OTHER_TENANT


@pytest.mark.asyncio
async def test_sa_with_tenant_query_resolves_that_tenant_for_movement_and_expiry() -> None:
    from routers import reports

    with (
        patch.object(reports, "resolve_node_scope", new=AsyncMock(return_value=None)),
        patch.object(reports, "get_stock_movement", new=AsyncMock(return_value=[])) as mv,
        patch.object(reports, "get_expiry_alerts", new=AsyncMock(return_value=[])) as ex,
    ):
        await reports.stock_movement.__wrapped__(
            request=_req(str(OTHER_TENANT)),
            date_from=None,
            date_to=None,
            level=None,
            node_id=None,
            warehouse_id=None,
            user=_sa(),
            db=_db(),
        )
        await reports.expiry_alerts.__wrapped__(
            request=_req(str(OTHER_TENANT)),
            window_days=30,
            level=None,
            node_id=None,
            warehouse_id=None,
            user=_sa(),
            db=_db(),
        )
    assert mv.await_args.args[1] == OTHER_TENANT
    assert ex.await_args.args[1] == OTHER_TENANT


@pytest.mark.asyncio
async def test_sa_with_tenant_query_resolves_that_tenant_for_filter_options() -> None:
    from routers import reports

    with (
        patch.object(reports, "resolve_node_scope", new=AsyncMock(return_value=None)),
        patch.object(
            reports,
            "filter_options",
            new=AsyncMock(return_value=SimpleNamespace(levels=[], nodes=[])),
        ) as fo,
    ):
        await reports.report_filter_options.__wrapped__(
            request=_req(str(OTHER_TENANT)), user=_sa(), db=_db()
        )
    assert fo.await_args.args[1] == str(OTHER_TENANT)


@pytest.mark.asyncio
async def test_sa_tenant_query_is_used_for_the_filter_scope_lookup() -> None:
    """The level/node/warehouse filter is looked up in the viewed tenant."""
    from routers import reports

    with (
        patch.object(reports, "resolve_node_scope", new=AsyncMock(return_value=None)),
        patch.object(reports, "filter_scope", new=AsyncMock(return_value=None)) as fs,
        patch.object(reports, "get_inventory_valuation", new=AsyncMock(return_value=[])),
    ):
        await reports.inventory_valuation.__wrapped__(
            request=_req(str(OTHER_TENANT)),
            level=2,
            node_id=NODE,
            warehouse_id=None,
            user=_sa(),
            db=_db(),
        )
    assert fs.await_args.args[1] == str(OTHER_TENANT)


async def _call_route(name: str, request: SimpleNamespace, user) -> object:
    from routers import reports

    route = getattr(reports, name).__wrapped__
    if name == "report_filter_options":
        return await route(request=request, user=user, db=_db())
    extra = {
        "inventory_valuation": {},
        "stock_movement": {"date_from": None, "date_to": None},
        "expiry_alerts": {"window_days": 30},
    }[name]
    return await route(
        request=request, level=None, node_id=None, warehouse_id=None, user=user, db=_db(), **extra
    )


_ALL_ROUTES = ["report_filter_options", "inventory_valuation", "stock_movement", "expiry_alerts"]


@pytest.mark.asyncio
@pytest.mark.parametrize("route", _ALL_ROUTES)
async def test_sa_without_tenant_query_is_422_tenant_required(route: str) -> None:
    with pytest.raises(HTTPException) as exc:
        await _call_route(route, _req(), _sa())
    assert exc.value.status_code == 422
    assert exc.value.detail == {"code": "TENANT_REQUIRED"}


@pytest.mark.asyncio
async def test_sa_with_malformed_tenant_query_is_422_tenant_required() -> None:
    with pytest.raises(HTTPException) as exc:
        await _call_route("inventory_valuation", _req("not-a-uuid"), _sa())
    assert exc.value.status_code == 422
    assert exc.value.detail == {"code": "TENANT_REQUIRED"}


@pytest.mark.asyncio
async def test_ta_ignores_a_different_tenant_in_the_query() -> None:
    from routers import reports

    with (
        patch.object(reports, "resolve_node_scope", new=AsyncMock(return_value=None)),
        patch.object(reports, "get_inventory_valuation", new=AsyncMock(return_value=[])) as q,
    ):
        await reports.inventory_valuation.__wrapped__(
            request=_req(str(OTHER_TENANT)),
            level=None,
            node_id=None,
            warehouse_id=None,
            user=_user("TA"),
            db=_db(),
        )
    assert q.await_args.args[1] == TENANT


# ── Dispatch summary (2026-10-22) ───────────────────────────────────────────

TO_ID = "40000000-0000-0000-0000-00000000000d"


@pytest.mark.asyncio
async def test_dispatch_route_passes_scope_product_and_one_dispatch() -> None:
    from routers import reports

    with (
        patch.object(reports, "resolve_node_scope", new=AsyncMock(return_value={NODE})),
        patch.object(reports, "filter_scope", new=AsyncMock(return_value=None)),
        patch.object(reports, "get_dispatch_summary", new=AsyncMock(return_value=[])) as q,
    ):
        await reports.dispatch_summary.__wrapped__(
            request=_req(),
            date_from=None,
            date_to=None,
            product_id=NODE,
            transfer_order_id=TO_ID,
            level=None,
            node_id=None,
            warehouse_id=None,
            user=_user("WM"),
            db=_db(),
        )
    assert q.await_args.args[2] == {NODE}
    assert q.await_args.kwargs["product_id"] == NODE
    assert q.await_args.kwargs["transfer_order_id"] == TO_ID


@pytest.mark.asyncio
async def test_dispatch_route_rejects_malformed_product_filter() -> None:
    from routers import reports

    with pytest.raises(HTTPException) as exc:
        await reports.dispatch_summary.__wrapped__(
            request=_req(),
            date_from=None,
            date_to=None,
            product_id="not-a-uuid",
            transfer_order_id=None,
            level=None,
            node_id=None,
            warehouse_id=None,
            user=_user("TA"),
            db=_db(),
        )
    assert exc.value.status_code == 422
    assert exc.value.detail == {"code": "INVALID_FILTER", "field": "product_id"}


# ── Lot trace (2026-10-22) ──────────────────────────────────────────────────

PRODUCT_ID = "50000000-0000-0000-0000-00000000000e"


@pytest.mark.asyncio
async def test_lot_trace_unknown_lot_is_404() -> None:
    from routers import reports

    with (
        patch.object(reports, "get_lot_header", new=AsyncMock(return_value=None)),
        pytest.raises(HTTPException) as exc,
    ):
        await reports.lot_trace.__wrapped__(
            request=_req(),
            product_id=PRODUCT_ID,
            lot_number="NOPE",
            date_from=None,
            date_to=None,
            level=None,
            node_id=None,
            warehouse_id=None,
            user=_user("TA"),
            db=_db(),
        )
    assert exc.value.status_code == 404
    assert exc.value.detail == {"code": "LOT_NOT_FOUND"}


@pytest.mark.asyncio
async def test_lot_trace_requires_a_valid_product() -> None:
    from routers import reports

    with pytest.raises(HTTPException) as exc:
        await reports.lot_trace.__wrapped__(
            request=_req(),
            product_id=None,
            lot_number="LOT-1",
            date_from=None,
            date_to=None,
            level=None,
            node_id=None,
            warehouse_id=None,
            user=_user("TA"),
            db=_db(),
        )
    assert exc.value.status_code == 422
    assert exc.value.detail == {"code": "INVALID_FILTER", "field": "product_id"}
