"""RB-2 G2 and G4 (2026-10-22).

G2: alerts, forecast and cross-warehouse stock keep only the warehouses inside
the caller's node scope (resolve_node_scope). None means tenant-wide.
G4: PATCH /lots/{id}/expiry checks every warehouse holding the lot against the
caller's scope, because product:update is tenant-wide.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import inventory_analytics as svc

TENANT = "10000000-0000-0000-0000-000000000001"
PRODUCT = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
WH_IN = "20000000-0000-0000-0000-00000000000a"
WH_OUT = "30000000-0000-0000-0000-00000000000b"


def _stock(warehouse_id: str, qty: str = "5"):
    from schemas.analytics import InventoryStockOut

    return InventoryStockOut(
        product_id=PRODUCT,
        product_name="Cement",
        product_sku="CEM",
        warehouse_id=uuid.UUID(warehouse_id),
        warehouse_name="W",
        warehouse_type="WAREHOUSE",
        current_stock=Decimal(qty),
    )


def _session_with_product():
    session = MagicMock()
    result = MagicMock()
    result.fetchone.return_value = SimpleNamespace(id=PRODUCT, name="Cement", sku="CEM")
    result.fetchall.return_value = []
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.mark.asyncio
async def test_cross_warehouse_keeps_only_scoped_warehouses() -> None:
    stock = [_stock(WH_IN, "5"), _stock(WH_OUT, "7")]
    with patch.object(svc, "get_stock", new=AsyncMock(return_value=stock)):
        out = await svc.get_cross_warehouse_stock(
            _session_with_product(), TENANT, PRODUCT, scope={WH_IN.lower()}
        )
    assert [str(w.warehouse_id) for w in out.warehouses] == [WH_IN]
    assert out.total_stock == Decimal("5")


@pytest.mark.asyncio
async def test_cross_warehouse_tenant_wide_when_scope_is_none() -> None:
    stock = [_stock(WH_IN, "5"), _stock(WH_OUT, "7")]
    with patch.object(svc, "get_stock", new=AsyncMock(return_value=stock)):
        out = await svc.get_cross_warehouse_stock(_session_with_product(), TENANT, PRODUCT)
    assert len(out.warehouses) == 2
    assert out.total_stock == Decimal("12")


@pytest.mark.asyncio
async def test_alerts_drop_warehouses_outside_scope() -> None:
    stock = [_stock(WH_IN, "1"), _stock(WH_OUT, "1")]
    products_result = MagicMock()
    products_result.fetchall.return_value = [
        SimpleNamespace(id=PRODUCT, reorder_point=10, reorder_quantity=20)
    ]
    session = MagicMock()
    session.execute = AsyncMock(return_value=products_result)
    with patch.object(svc, "get_stock", new=AsyncMock(return_value=stock)):
        alerts = await svc.get_alerts(session, TENANT, scope={WH_IN.lower()})
    assert [str(a.warehouse_id) for a in alerts] == [WH_IN]


@pytest.mark.asyncio
async def test_forecast_drops_warehouses_outside_scope() -> None:
    stock = [_stock(WH_IN, "1"), _stock(WH_OUT, "1")]
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(fetchall=lambda: [], fetchone=lambda: None))
    with patch.object(svc, "get_stock", new=AsyncMock(return_value=stock)):
        out = await svc.get_forecast(session, TENANT, scope={WH_IN.lower()})
    assert {str(f.warehouse_id) for f in out} <= {WH_IN}


@pytest.mark.asyncio
async def test_lot_expiry_denied_when_lot_sits_outside_scope() -> None:
    from fastapi import HTTPException

    from routers import lots

    lot_rows = MagicMock()
    lot_rows.fetchall.return_value = [SimpleNamespace(warehouse_id=uuid.UUID(WH_OUT))]
    session = MagicMock()
    session.execute = AsyncMock(return_value=lot_rows)
    user = SimpleNamespace(role="WM", tenant_id=TENANT, warehouse_id=WH_IN)
    body = SimpleNamespace(expiry_date="2027-01-01")
    with (
        patch.object(lots, "feature_lot_tracking_enabled", return_value=True),
        patch.object(lots, "resolve_node_scope", new=AsyncMock(return_value={WH_IN.lower()})),
        patch.object(lots, "set_lot_expiry", new=AsyncMock()) as set_expiry,
    ):
        with pytest.raises(HTTPException) as exc:
            await lots.patch_lot_expiry.__wrapped__(
                lot_id=uuid.uuid4(), body=body, user=user, db=session
            )
    assert exc.value.status_code == 403
    assert exc.value.detail == {"code": "ABAC_DENIED"}
    set_expiry.assert_not_awaited()


@pytest.mark.asyncio
async def test_lot_expiry_allowed_tenant_wide() -> None:
    from routers import lots

    session = MagicMock()
    user = SimpleNamespace(role="TA", tenant_id=TENANT, warehouse_id=None)
    with (
        patch.object(lots, "feature_lot_tracking_enabled", return_value=True),
        patch.object(lots, "resolve_node_scope", new=AsyncMock(return_value=None)),
        patch.object(
            lots,
            "set_lot_expiry",
            new=AsyncMock(
                return_value={
                    "lot_id": uuid.uuid4(),
                    "lot_number": "L1",
                    "product_id": uuid.uuid4(),
                    "expiry_date": "2027-01-01",
                }
            ),
        ) as set_expiry,
    ):
        await lots.patch_lot_expiry.__wrapped__(
            lot_id=uuid.uuid4(),
            body=SimpleNamespace(expiry_date="2027-01-01"),
            user=user,
            db=session,
        )
    set_expiry.assert_awaited_once()
