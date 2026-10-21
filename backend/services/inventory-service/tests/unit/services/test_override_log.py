"""Override log + FEFO compliance summary (services/override_log_service.py and the
GET /inventory/lots/overrides[/summary] routes in routers/lots.py).

Uses the inv_app fixture (not a fresh `from main import app`) per conftest.py.
RBAC is driven by a small grant table mirroring seed_permissions.py for the
roles used here (WM has no report:dispatch_summary).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from dependencies import get_current_user, get_db_session, get_read_db_session
from schemas.inventory import OverrideLogOut, OverrideSummaryOut
from services import override_log_service as svc
from services.override_log_service import (
    compliance_rate,
    list_overrides,
    override_summary,
    resolve_period,
)

TENANT_ID = "10000000-0000-0000-0000-000000000001"
NODE_ID = "AAAAAAAA-0000-0000-0000-000000000001"  # JWT casing differs from the DB's
CHILD_ID = "aaaaaaaa-0000-0000-0000-000000000002"
OUTSIDE_ID = "bbbbbbbb-0000-0000-0000-000000000009"

_GRANTS = {("TA", "report:dispatch_summary"), ("RM", "report:dispatch_summary")}


def _user(role, node=None):
    return SimpleNamespace(
        user_id=f"u-{role.lower()}",
        tenant_id=TENANT_ID,
        role=role,
        warehouse_id=node,
        region_id=None,
    )


def _session():
    """Every execute() returns zero counts / no rows."""
    row = SimpleNamespace(n=0, decisions=0, overridden=0)
    result = MagicMock()
    result.fetchone.return_value = row
    result.fetchall.return_value = []
    s = MagicMock()
    s.execute = AsyncMock(return_value=result)
    return s


def _statements(session):
    return [(str(c.args[0]), c.args[1]) for c in session.execute.call_args_list]


@pytest.fixture
def subtree():
    with patch.object(
        svc, "_subtree", new=AsyncMock(return_value={NODE_ID.lower(), CHILD_ID})
    ) as m:
        yield m


@pytest.mark.unit
class TestComplianceRate:
    def test_no_decisions_is_null(self) -> None:
        assert compliance_rate(0, 0) is None

    def test_ten_decisions_two_overridden(self) -> None:
        assert compliance_rate(10, 2) == 0.8

    def test_rounded_to_four_places(self) -> None:
        assert compliance_rate(3, 1) == 0.6667

    def test_all_overridden_is_zero(self) -> None:
        assert compliance_rate(4, 4) == 0.0


@pytest.mark.unit
class TestPeriod:
    def test_default_is_last_30_days_ending_today(self) -> None:
        start, end = resolve_period(None, None, today=date(2026, 10, 14))
        assert end == date(2026, 10, 14)
        assert start == date(2026, 9, 15)
        assert (end - start).days + 1 == 30

    def test_from_after_to_is_422(self) -> None:
        with pytest.raises(HTTPException) as e:
            resolve_period(date(2026, 10, 2), date(2026, 10, 1))
        assert e.value.status_code == 422

    def test_400_day_range_is_422(self) -> None:
        with pytest.raises(HTTPException) as e:
            resolve_period(date(2025, 9, 1), date(2026, 10, 5))
        assert e.value.status_code == 422

    def test_366_day_range_is_allowed(self) -> None:
        end = date(2026, 10, 14)
        assert resolve_period(end - timedelta(days=366), end) == (end - timedelta(days=366), end)

    async def test_service_rejects_bad_period_before_any_query(self) -> None:
        s = _session()
        with pytest.raises(HTTPException) as e:
            await list_overrides(
                s, _user("TA"), TENANT_ID, date_from=date(2026, 10, 2), date_to=date(2026, 10, 1)
            )
        assert e.value.status_code == 422
        s.execute.assert_not_called()


@pytest.mark.unit
class TestScope:
    async def test_rm_with_node_gets_subtree_filter(self, subtree) -> None:
        s = _session()
        await list_overrides(s, _user("RM", NODE_ID), TENANT_ID)
        subtree.assert_awaited_once()
        for sql, params in _statements(s)[:2]:
            assert "o.warehouse_id = ANY(" in sql
            assert params["subtree"] == sorted({NODE_ID.lower(), CHILD_ID})

    async def test_rm_summary_filters_all_three_sources(self, subtree) -> None:
        s = _session()
        await override_summary(s, _user("RM", NODE_ID), TENANT_ID)
        sqls = [sql for sql, _ in _statements(s)]
        assert len(sqls) == 4  # (transfer, issue) x (overall, FEFO)
        assert any("a.from_warehouse_id = ANY(" in q for q in sqls)
        assert any("t.warehouse_id = ANY(" in q for q in sqls)

    async def test_rm_warehouse_outside_subtree_is_403(self, subtree) -> None:
        s = _session()
        with pytest.raises(HTTPException) as e:
            await list_overrides(s, _user("RM", NODE_ID), TENANT_ID, warehouse_id=OUTSIDE_ID)
        assert e.value.status_code == 403
        assert e.value.detail == {"code": "WAREHOUSE_OUT_OF_SCOPE"}
        s.execute.assert_not_called()

    async def test_rm_warehouse_inside_subtree_compares_lowercased(self, subtree) -> None:
        s = _session()
        await list_overrides(s, _user("RM", NODE_ID), TENANT_ID, warehouse_id=NODE_ID)
        assert _statements(s)[0][1]["wh"] == NODE_ID.lower()

    @pytest.mark.parametrize("role", ["WM", "LM", "SA_GT", "RT"])
    async def test_facility_role_without_node_is_empty(self, role, subtree) -> None:
        s = _session()
        out = await list_overrides(s, _user(role), TENANT_ID)
        assert out.total == 0 and out.rows == []
        summary = await override_summary(s, _user(role), TENANT_ID)
        assert summary.overall.decisions == 0
        assert summary.overall.compliance_rate is None
        s.execute.assert_not_called()

    async def test_facility_role_with_node_is_subtree_filtered(self, subtree) -> None:
        s = _session()
        await list_overrides(s, _user("WM", NODE_ID), TENANT_ID)
        assert "subtree" in _statements(s)[0][1]

    async def test_rm_without_node_is_tenant_wide(self, subtree) -> None:
        s = _session()
        await list_overrides(s, _user("RM"), TENANT_ID)
        subtree.assert_not_awaited()
        assert "subtree" not in _statements(s)[0][1]

    @pytest.mark.parametrize("role", ["TA", "NM", "AU", "SA"])
    async def test_tenant_wide_roles_have_no_subtree_filter(self, role, subtree) -> None:
        s = _session()
        await list_overrides(s, _user(role, NODE_ID), TENANT_ID)
        subtree.assert_not_awaited()
        for sql, params in _statements(s):
            assert "subtree" not in params
            assert "ANY(" not in sql.split("WHERE", 1)[1].split("ORDER BY")[0]

    async def test_ta_warehouse_filter_is_plain_equality(self, subtree) -> None:
        s = _session()
        await list_overrides(s, _user("TA"), TENANT_ID, warehouse_id=OUTSIDE_ID)
        assert _statements(s)[0][1]["wh"] == OUTSIDE_ID


@pytest.mark.unit
class TestQueriesCarryTenant:
    async def test_list_queries_filter_by_tenant(self) -> None:
        s = MagicMock()
        row = SimpleNamespace(
            id="00000000-0000-0000-0000-0000000000d1",
            created_at=datetime.now(timezone.utc),
            overridden_by_name="A B",
            product_id="00000000-0000-0000-0000-0000000000a1",
            product_name="P",
            product_sku="S",
            warehouse_id="00000000-0000-0000-0000-0000000000b1",
            warehouse_name="WH",
            strategy="FEFO",
            movement_type="ISSUE",
            reference_id=None,
            requested_qty=1,
            suggested='[{"lot_id": "00000000-0000-0000-0000-0000000000c1", '
            '"lot_number": "OLD", "quantity": "1"}]',
            chosen=[
                {
                    "lot_id": "00000000-0000-0000-0000-0000000000c2",
                    "lot_number": None,
                    "quantity": "1",
                }
            ],
            reason="r",
        )
        lots = [
            SimpleNamespace(id="00000000-0000-0000-0000-0000000000c1", lot_number="L-1"),
            SimpleNamespace(id="00000000-0000-0000-0000-0000000000c2", lot_number="L-2"),
        ]
        results = [SimpleNamespace(n=1), [row], lots]

        async def _execute(stmt, params=None):
            r = MagicMock()
            nxt = results.pop(0)
            r.fetchone.return_value = nxt
            r.fetchall.return_value = nxt
            return r

        s.execute = AsyncMock(side_effect=_execute)
        out = await list_overrides(s, _user("TA"), TENANT_ID)

        assert out.total == 1
        item = out.rows[0]
        assert item.overridden_by == "A B"
        assert item.product.sku == "S" and item.warehouse.name == "WH"
        assert [x.lot_number for x in item.suggested] == ["L-1"]  # joined, not the stored one
        assert [x.lot_number for x in item.chosen] == ["L-2"]
        stmts = _statements(s)
        assert len(stmts) == 3
        for sql, params in stmts:
            assert "tenant_id = :tid" in sql
            assert params["tid"] == TENANT_ID

    async def test_summary_queries_filter_by_tenant(self) -> None:
        s = _session()
        out = await override_summary(s, _user("TA"), TENANT_ID)
        assert isinstance(out, OverrideSummaryOut)
        assert set(out.by_movement) == {"TRANSFER", "ISSUE"}
        for sql, params in _statements(s):
            assert "tenant_id = :tid" in sql
            assert params["tid"] == TENANT_ID

    async def test_fefo_counts_join_products_overall_does_not(self) -> None:
        s = _session()
        await override_summary(s, _user("TA"), TENANT_ID)
        sqls = [sql for sql, _ in _statements(s)]
        assert sum("p.dispatch_strategy = 'FEFO'" in q for q in sqls) == 2
        assert sum("JOIN products" in q for q in sqls) == 2

    async def test_issue_overridden_counted_from_same_ledger_rows_as_decisions(self) -> None:
        """An override whose ledger rows fall outside the period is not counted:
        the Issue overridden count is read from the SAME statement (same period,
        scope and FEFO filter) as the Issue decisions, never from the override
        table's own created_at."""
        s = _session()
        await override_summary(s, _user("TA"), TENANT_ID)
        stmts = _statements(s)
        issue_sqls = [(q, p) for q, p in stmts if "FROM inventory_transactions t" in q]
        assert len(issue_sqls) == 2  # overall, FEFO
        for sql, params in issue_sqls:
            assert "AS decisions" in sql and "AS overridden" in sql
            assert "t.transaction_date >= :df AND t.transaction_date <= :dt" in sql
            assert "o.reference_id = t.reference_id" in sql
            assert "o.tenant_id = t.tenant_id AND o.movement_type = 'ISSUE'" in sql
            assert "ts_from" not in params  # period is the ledger date, not created_at
        # no separate query counts ISSUE overrides by lot_allocation_overrides.created_at
        for sql, _ in stmts:
            assert not (
                "FROM lot_allocation_overrides o " in sql
                and "o.created_at" in sql
                and "count(" in sql
            )

    async def test_issue_overridden_never_exceeds_decisions(self) -> None:
        # one Issue decision in the period, one matching override: 1 of 1, never more.
        result = MagicMock()
        result.fetchone.return_value = SimpleNamespace(decisions=1, overridden=1)
        s = MagicMock()
        s.execute = AsyncMock(return_value=result)
        out = await override_summary(s, _user("TA"), TENANT_ID)
        issue = out.by_movement["ISSUE"]
        assert issue.overridden <= issue.decisions
        assert issue.compliance_rate == 0.0

    async def test_sa_without_tenant_is_422(self) -> None:
        s = _session()
        with pytest.raises(HTTPException) as e:
            await list_overrides(s, _user("SA"), None)
        assert e.value.status_code == 422
        s.execute.assert_not_called()


@pytest.fixture
def make_client(inv_app):
    """make_client(role, session) -> AsyncClient with RBAC from _GRANTS."""

    def _make(role, session):
        async def _db_gen():
            yield session

        inv_app.dependency_overrides[get_current_user] = lambda: _user(role)
        inv_app.dependency_overrides[get_db_session] = _db_gen
        inv_app.dependency_overrides[get_read_db_session] = _db_gen
        return AsyncClient(transport=ASGITransport(app=inv_app), base_url="http://test")

    async def _grant(role, action_id):
        if (role, action_id) not in _GRANTS:
            return None
        g = MagicMock()
        g.grant_type = "FULL"
        return g

    with (
        patch(
            "shared.permissions.middleware.get_role_permission", new=AsyncMock(side_effect=_grant)
        ),
        patch("shared.permissions.middleware.audit_log", new=AsyncMock()),
    ):
        try:
            yield _make
        finally:
            inv_app.dependency_overrides.clear()


@pytest.mark.unit
class TestRoutes:
    @pytest.mark.parametrize(
        "path", ["/api/v1/inventory/lots/overrides", "/api/v1/inventory/lots/overrides/summary"]
    )
    async def test_wm_without_permission_is_403(self, make_client, path) -> None:
        s = _session()
        async with make_client("WM", s) as c:
            resp = await c.get(path)
        assert resp.status_code == 403
        s.execute.assert_not_called()

    async def test_ta_list_passes_tenant_and_filters(self, make_client) -> None:
        out = OverrideLogOut(total=0, rows=[])
        async with make_client("TA", _session()) as c:
            with patch("routers.lots.list_overrides", new=AsyncMock(return_value=out)) as m:
                resp = await c.get(
                    "/api/v1/inventory/lots/overrides"
                    "?strategy=FEFO&limit=10&offset=5&date_from=2026-10-01&date_to=2026-10-10"
                )
        assert resp.status_code == 200
        assert resp.json()["data"] == {"total": 0, "rows": []}
        args, kwargs = m.call_args
        assert str(args[2]) == TENANT_ID
        assert kwargs["strategy"] == "FEFO"
        assert kwargs["limit"] == 10 and kwargs["offset"] == 5
        assert kwargs["date_from"] == date(2026, 10, 1)

    async def test_summary_route_is_not_shadowed(self, make_client) -> None:
        async with make_client("TA", _session()) as c:
            resp = await c.get("/api/v1/inventory/lots/overrides/summary")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["overall"] == {"decisions": 0, "overridden": 0, "compliance_rate": None}

    async def test_limit_over_200_is_422(self, make_client) -> None:
        async with make_client("TA", _session()) as c:
            resp = await c.get("/api/v1/inventory/lots/overrides?limit=201")
        assert resp.status_code == 422
