"""Router-level tests for GET /api/v1/inventory/dispatch/preview.

Uses the inv_app fixture (not a fresh `from main import app`) per the
convention established in test_permissions.py / conftest.py.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from dependencies import get_current_user, get_read_db_session

URL = "/api/v1/inventory/dispatch/preview"

PRODUCT_ID = "aaaaaaaa-0000-0000-0000-000000000001"
WAREHOUSE_A = "20000000-0000-0000-0000-000000000001"
WAREHOUSE_B = "20000000-0000-0000-0000-000000000002"

LOT_OPENING = "30000000-0000-0000-0000-000000000001"
LOT_DATED = "30000000-0000-0000-0000-000000000002"
LOT_EXPIRED = "30000000-0000-0000-0000-000000000003"


def _mock_full_grant():
    grant = MagicMock()
    grant.grant_type = "FULL"
    return grant


def _lot_row(lot_id, lot_number, quantity, expiry_date=None, day=1):
    return MagicMock(
        lot_id=lot_id,
        lot_number=lot_number,
        expiry_date=expiry_date,
        first_received_at=datetime(2026, 1, day),
        quantity=Decimal(quantity),
    )


_LOT_ROWS = [
    _lot_row(LOT_DATED, "L-DATED", "10", expiry_date=date(2999, 1, 1), day=2),
    _lot_row(LOT_EXPIRED, "L-EXPIRED", "4", expiry_date=date(2000, 1, 1), day=3),
    _lot_row(LOT_OPENING, "OPENING-MWH", "6", day=1),
]


def _make_db(product_row):
    """Mock read session: answers the products and lot_balances queries by SQL text."""
    db = AsyncMock()

    async def _execute(statement, params=None):
        sql = str(statement)
        result = MagicMock()
        result.fetchall.return_value = []
        result.fetchone.return_value = None
        if "FROM products" in sql:
            result.fetchone.return_value = product_row
        elif "FROM lot_balances" in sql:
            result.fetchall.return_value = _LOT_ROWS
        return result

    db.execute = AsyncMock(side_effect=_execute)
    return db


def _product(batch_tracking=True, expiry_tracking=True, dispatch_strategy="FEFO"):
    return MagicMock(
        batch_tracking=batch_tracking,
        expiry_tracking=expiry_tracking,
        dispatch_strategy=dispatch_strategy,
    )


@pytest.fixture
def make_client(inv_app):
    """Factory: async client for a given user + product row."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _make(user, product_row):
        db = _make_db(product_row)

        async def _db_gen():
            yield db

        inv_app.dependency_overrides[get_current_user] = lambda: user
        inv_app.dependency_overrides[get_read_db_session] = _db_gen
        try:
            with (
                patch(
                    "shared.permissions.middleware.get_role_permission",
                    new=AsyncMock(return_value=_mock_full_grant()),
                ),
                patch("shared.permissions.middleware.audit_log", new=AsyncMock()),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=inv_app), base_url="http://test"
                ) as ac:
                    yield ac, db
        finally:
            inv_app.dependency_overrides.clear()

    return _make


def _params(quantity="12", warehouse_id=WAREHOUSE_A):
    return {"product_id": PRODUCT_ID, "warehouse_id": warehouse_id, "quantity": quantity}


@pytest.mark.unit
class TestDispatchPreview:
    async def test_200_shape_fefo(self, make_client, wm_user) -> None:
        async with make_client(wm_user, _product()) as (client, _db):
            resp = await client.get(URL, params=_params("12"))

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert set(data) == {
            "product_id",
            "warehouse_id",
            "quantity",
            "strategy",
            "strategy_source",
            "lines",
            "shortfall",
            "expired_skipped",
            "available_total",
        }
        assert data["product_id"] == PRODUCT_ID
        assert data["warehouse_id"] == WAREHOUSE_A
        assert data["strategy"] == "FEFO"
        assert data["strategy_source"] == "FORCED"
        assert [(line["lot_number"], Decimal(line["quantity"])) for line in data["lines"]] == [
            ("OPENING-MWH", Decimal("6")),
            ("L-DATED", Decimal("6")),
        ]
        assert set(data["lines"][0]) == {"lot_id", "lot_number", "expiry_date", "quantity"}
        assert data["lines"][0]["expiry_date"] is None
        assert data["lines"][1]["expiry_date"] == "2999-01-01"
        assert [lot["lot_number"] for lot in data["expired_skipped"]] == ["L-EXPIRED"]
        assert Decimal(data["shortfall"]) == Decimal("0")
        assert Decimal(data["available_total"]) == Decimal("16")

    async def test_shortfall_reported_not_an_error(self, make_client, wm_user) -> None:
        async with make_client(wm_user, _product()) as (client, _db):
            resp = await client.get(URL, params=_params("20"))

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert Decimal(data["shortfall"]) == Decimal("4")
        assert Decimal(data["available_total"]) == Decimal("16")

    async def test_product_strategy_lifo(self, make_client, wm_user) -> None:
        product = _product(expiry_tracking=False, dispatch_strategy="LIFO")
        async with make_client(wm_user, product) as (client, _db):
            resp = await client.get(URL, params=_params("5"))

        data = resp.json()["data"]
        assert (data["strategy"], data["strategy_source"]) == ("LIFO", "PRODUCT")
        assert [line["lot_number"] for line in data["lines"]] == ["L-DATED"]

    async def test_preview_never_locks(self, make_client, wm_user) -> None:
        async with make_client(wm_user, _product()) as (client, db):
            await client.get(URL, params=_params("12"))

        statements = [str(c.args[0]) for c in db.execute.call_args_list]
        assert any("FROM lot_balances" in s for s in statements)
        assert not any("FOR UPDATE" in s for s in statements)

    async def test_non_batch_product_returns_empty_plan(self, make_client, wm_user) -> None:
        product = _product(batch_tracking=False, expiry_tracking=False, dispatch_strategy=None)
        async with make_client(wm_user, product) as (client, db):
            resp = await client.get(URL, params=_params("7"))

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["strategy"] is None
        assert data["strategy_source"] == "NOT_BATCH"
        assert data["lines"] == []
        assert data["expired_skipped"] == []
        assert Decimal(data["shortfall"]) == Decimal("7")
        assert Decimal(data["available_total"]) == Decimal("0")
        assert not any("FROM lot_balances" in str(c.args[0]) for c in db.execute.call_args_list)

    async def test_unknown_product_returns_404(self, make_client, wm_user) -> None:
        async with make_client(wm_user, None) as (client, _db):
            resp = await client.get(URL, params=_params())

        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "PRODUCT_NOT_FOUND"

    @pytest.mark.parametrize("quantity", ["0", "-1"])
    async def test_quantity_not_positive_returns_422(self, make_client, wm_user, quantity) -> None:
        async with make_client(wm_user, _product()) as (client, _db):
            resp = await client.get(URL, params=_params(quantity))

        assert resp.status_code == 422

    @pytest.mark.parametrize("missing", ["product_id", "warehouse_id", "quantity"])
    async def test_missing_required_param_returns_422(self, make_client, wm_user, missing) -> None:
        params = _params()
        params.pop(missing)
        async with make_client(wm_user, _product()) as (client, _db):
            resp = await client.get(URL, params=params)

        assert resp.status_code == 422

    async def test_facility_scoped_user_outside_subtree_returns_403(
        self, make_client, wm_user
    ) -> None:
        """WM scoped to WAREHOUSE_A asking for WAREHOUSE_B: the warehouse_id
        query kwarg goes through check_permission's node+descendant traversal
        (get_descendant_node_ids) — WAREHOUSE_B is not in the subtree."""
        with patch(
            "shared.permissions.middleware.get_descendant_node_ids",
            new=AsyncMock(return_value={WAREHOUSE_A}),
        ):
            async with make_client(wm_user, _product()) as (client, db):
                resp = await client.get(URL, params=_params(warehouse_id=WAREHOUSE_B))

        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "ABAC_DENIED"
        assert resp.json()["detail"]["reason"] == "warehouse scope"
        assert not any("FROM lot_balances" in str(c.args[0]) for c in db.execute.call_args_list)

    async def test_facility_scoped_user_inside_subtree_allowed(self, make_client, wm_user) -> None:
        with patch(
            "shared.permissions.middleware.get_descendant_node_ids",
            new=AsyncMock(return_value={WAREHOUSE_A, WAREHOUSE_B}),
        ):
            async with make_client(wm_user, _product()) as (client, _db):
                resp = await client.get(URL, params=_params(warehouse_id=WAREHOUSE_B))

        assert resp.status_code == 200
