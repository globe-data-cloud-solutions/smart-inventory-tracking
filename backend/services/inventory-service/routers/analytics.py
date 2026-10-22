"""Analytics and stock-level query endpoints.

All routes use the read replica session where possible.
The effective_tenant_id() utility allows SA to query across tenants.
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_read_db_session
from dependencies import get_current_user
from shared.permissions.hierarchy_service import resolve_node_scope
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse
from shared.utils.tenant_scope import effective_tenant_id
from schemas.analytics import (
    CrossWarehouseStockOut,
    ForecastOut,
    InventoryStockOut,
    ReorderAlertOut,
    TransferHistoryItem,
    WarehouseOut,
)
from services.inventory_analytics import (
    get_alerts,
    get_cross_warehouse_stock,
    get_forecast,
    get_stock,
    get_transfer_history,
)

router = APIRouter()


@router.get("/stock", response_model=SuccessResponse[List[InventoryStockOut]])
@require_permission(PERMISSIONS.INVENTORY_VIEW_BALANCE)
async def stock_levels(
    warehouse_id: Optional[uuid.UUID] = Query(None),
    tenant_id: Optional[uuid.UUID] = Query(None, description="SA only — filter to specific tenant"),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_read_db_session),
) -> SuccessResponse[List[InventoryStockOut]]:
    """Current stock levels with pending outbound and inbound quantities."""
    tid = effective_tenant_id(user, tenant_id)
    data = await get_stock(db, tid, warehouse_id=warehouse_id)
    return SuccessResponse(data=data)


@router.get("/alerts", response_model=SuccessResponse[List[ReorderAlertOut]])
@require_permission(PERMISSIONS.REPORT_LOW_STOCK)
async def reorder_alerts(
    tenant_id: Optional[uuid.UUID] = Query(None),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_read_db_session),
) -> SuccessResponse[List[ReorderAlertOut]]:
    """All product/warehouse pairs at or below their reorder point, sorted by shortfall."""
    tid = effective_tenant_id(user, tenant_id)
    scope = await resolve_node_scope(db, user)
    data = await get_alerts(db, tid, scope=scope)
    return SuccessResponse(data=data)


@router.get("/forecast", response_model=SuccessResponse[List[ForecastOut]])
@require_permission(PERMISSIONS.AI_FORECAST_VIEW)
async def demand_forecast(
    product_id: Optional[uuid.UUID] = Query(None),
    days: int = Query(30, ge=1, le=365),
    tenant_id: Optional[uuid.UUID] = Query(None),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_read_db_session),
) -> SuccessResponse[List[ForecastOut]]:
    """Average daily consumption and estimated days until stockout per location."""
    tid = effective_tenant_id(user, tenant_id)
    scope = await resolve_node_scope(db, user)
    data = await get_forecast(db, tid, product_id=product_id, days=days, scope=scope)
    return SuccessResponse(data=data)


@router.get("/cross-warehouse/{product_id}", response_model=SuccessResponse[CrossWarehouseStockOut])
@require_permission(PERMISSIONS.INVENTORY_VIEW)
async def cross_warehouse_stock(
    product_id: uuid.UUID,
    tenant_id: Optional[uuid.UUID] = Query(None),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_read_db_session),
) -> SuccessResponse[CrossWarehouseStockOut]:
    """Stock of a single product across all warehouses."""
    tid = effective_tenant_id(user, tenant_id)
    scope = await resolve_node_scope(db, user)
    data = await get_cross_warehouse_stock(db, tid, product_id, scope=scope)
    return SuccessResponse(data=data)


@router.get("/warehouses", response_model=SuccessResponse[List[WarehouseOut]])
@require_permission(PERMISSIONS.INVENTORY_VIEW_BALANCE)
async def list_warehouses(
    tenant_id: Optional[uuid.UUID] = Query(None),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_read_db_session),
) -> SuccessResponse[List[WarehouseOut]]:
    """All active warehouses for the tenant with address and assigned manager name."""
    from sqlalchemy import text

    tid = effective_tenant_id(user, tenant_id)
    rows = (
        await db.execute(
            text("""
            SELECT n.id, n.name, 'WAREHOUSE' AS warehouse_type,
                   NULL::text AS address, NULL::text AS manager_name
            FROM organization_node n
            WHERE n.tenant_id = :tid AND n.is_active = true
            UNION ALL
            SELECT w.id, w.name, w.warehouse_type::text, w.address,
                   NULL::text AS manager_name
            FROM warehouses w
            WHERE w.tenant_id = :tid AND w.is_active = true
              AND NOT EXISTS (
                SELECT 1 FROM organization_node n2
                WHERE n2.id = w.id AND n2.tenant_id = :tid
              )
            ORDER BY name
        """),
            {"tid": str(tid)},
        )
    ).fetchall()
    return SuccessResponse(
        data=[
            WarehouseOut(
                id=r.id,
                name=r.name,
                warehouse_type=r.warehouse_type,
                address=r.address,
                manager_name=r.manager_name,
            )
            for r in rows
        ]
    )


@router.get("/transfer-history", response_model=SuccessResponse[List[TransferHistoryItem]])
@require_permission(PERMISSIONS.INVENTORY_VIEW_LEDGER)
async def transfer_history(
    product_id: uuid.UUID = Query(...),
    warehouse_id: uuid.UUID = Query(...),
    tenant_id: Optional[uuid.UUID] = Query(None),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_read_db_session),
) -> SuccessResponse[List[TransferHistoryItem]]:
    """Outbound transfer history for a product at a specific warehouse."""
    tid = effective_tenant_id(user, tenant_id)
    data = await get_transfer_history(db, tid, product_id, warehouse_id)
    return SuccessResponse(data=data)
