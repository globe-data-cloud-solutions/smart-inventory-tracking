"""Unit tests for services/inventory_analytics.get_lots().

The ACTIVE/DEPLETED/EXPIRED status and the include_depleted/status filters
are computed in SQL (see the CASE expression and WHERE clause in get_lots()),
so these tests mock session.execute and verify: (a) row->LotOut mapping for
each status value, and (b) that product_id/warehouse_id/status/include_depleted
are plumbed through to the query params exactly as the caller passed them.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

TENANT_ID    = "10000000-0000-0000-0000-000000000001"
PRODUCT_ID   = "aaaaaaaa-0000-0000-0000-000000000001"
WAREHOUSE_ID = "20000000-0000-0000-0000-000000000001"


def _lot_row(
    lot_id="30000000-0000-0000-0000-000000000001",
    lot_number="OPENING-MWH",
    product_id=PRODUCT_ID,
    product_name="Cement 50kg",
    product_sku="CEM-001",
    warehouse_id=WAREHOUSE_ID,
    warehouse_name="AW North",
    quantity=Decimal("10"),
    expiry_date=None,
    first_received_at=None,
    is_opening=False,
    status="ACTIVE",
):
    return MagicMock(
        lot_id=lot_id,
        lot_number=lot_number,
        product_id=product_id,
        product_name=product_name,
        product_sku=product_sku,
        warehouse_id=warehouse_id,
        warehouse_name=warehouse_name,
        quantity=quantity,
        expiry_date=expiry_date,
        first_received_at=first_received_at or datetime(2026, 1, 1),
        is_opening=is_opening,
        status=status,
    )


def _result(rows):
    r = MagicMock()
    r.fetchall.return_value = rows
    return r


@pytest.mark.unit
class TestGetLotsMapping:

    async def test_returns_lot_rows_with_computed_status(self) -> None:
        from services.inventory_analytics import get_lots

        session = AsyncMock()
        session.execute = AsyncMock(
            return_value=_result([
                _lot_row(status="ACTIVE"),
                _lot_row(lot_id="30000000-0000-0000-0000-000000000002",
                         lot_number="30250101-002", status="EXPIRED",
                         expiry_date=date(2025, 1, 1)),
            ])
        )

        result = await get_lots(session, TENANT_ID)

        assert [r.status for r in result] == ["ACTIVE", "EXPIRED"]
        assert result[0].lot_number == "OPENING-MWH"
        assert result[1].expiry_date == date(2025, 1, 1)

    async def test_depleted_hidden_by_default(self) -> None:
        """When the DB returns only non-DEPLETED rows (as the WHERE clause's
        include_depleted guard does when include_depleted=False), get_lots()
        passes them straight through without re-filtering."""
        from services.inventory_analytics import get_lots

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_result([_lot_row(status="ACTIVE")]))

        result = await get_lots(session, TENANT_ID, include_depleted=False)

        assert len(result) == 1
        assert result[0].status == "ACTIVE"
        _, params = session.execute.call_args.args
        assert params["include_depleted"] is False

    async def test_include_depleted_true_shows_depleted_row(self) -> None:
        from services.inventory_analytics import get_lots

        session = AsyncMock()
        session.execute = AsyncMock(
            return_value=_result([_lot_row(status="DEPLETED", quantity=Decimal("0"))])
        )

        result = await get_lots(session, TENANT_ID, include_depleted=True)

        assert len(result) == 1
        assert result[0].status == "DEPLETED"
        assert result[0].quantity == Decimal("0")
        _, params = session.execute.call_args.args
        assert params["include_depleted"] is True


@pytest.mark.unit
class TestGetLotsFilters:

    async def test_product_id_filter_passed_to_query(self) -> None:
        from services.inventory_analytics import get_lots

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_result([]))

        await get_lots(session, TENANT_ID, product_id=PRODUCT_ID)

        sql, params = session.execute.call_args.args
        assert params["pid"] == PRODUCT_ID
        assert "sl.product_id = :pid" in str(sql)

    async def test_warehouse_id_filter_passed_to_query(self) -> None:
        from services.inventory_analytics import get_lots

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_result([]))

        await get_lots(session, TENANT_ID, warehouse_id=WAREHOUSE_ID)

        sql, params = session.execute.call_args.args
        assert params["wid"] == WAREHOUSE_ID
        assert "lb.warehouse_id = :wid" in str(sql)

    async def test_status_filter_passed_to_query(self) -> None:
        from services.inventory_analytics import get_lots

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_result([]))

        await get_lots(session, TENANT_ID, status="EXPIRED")

        _, params = session.execute.call_args.args
        assert params["status"] == "EXPIRED"

    async def test_no_product_or_warehouse_filter_omits_params(self) -> None:
        from services.inventory_analytics import get_lots

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_result([]))

        await get_lots(session, TENANT_ID)

        _, params = session.execute.call_args.args
        assert "pid" not in params
        assert "wid" not in params
