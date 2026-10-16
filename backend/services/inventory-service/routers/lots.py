"""Lot read endpoint — /api/v1/inventory/lots.

Scoping mirrors GET /analytics/stock exactly: same permission
(inventory:view_balance) and the same warehouse_id-kwarg ABAC path through
require_permission -> check_permission (get_descendant_node_ids traversal
for FACILITY_SCOPED roles) in shared/permissions/middleware.py. No raw
warehouse_id equality check is added here.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_current_user, get_db_session, get_read_db_session
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse
from shared.utils.tenant_scope import effective_tenant_id
from routers.lot_settings import feature_lot_tracking_enabled
from schemas.analytics import ExpiryAlertsOut, LotOut
from schemas.inventory import (
    NearExpirySettingsOut,
    NearExpirySettingsRequest,
    OverrideLogOut,
    OverrideSummaryOut,
    SetLotExpiryOut,
    SetLotExpiryRequest,
)
from services.inventory_analytics import get_expiry_alerts, get_lots
from services.lot_expiry_service import (
    get_near_expiry_days,
    set_lot_expiry,
    set_near_expiry_days,
)
from services.override_log_service import list_overrides, override_summary

router = APIRouter()


@router.get("", response_model=SuccessResponse[List[LotOut]])
@require_permission(PERMISSIONS.INVENTORY_VIEW_BALANCE)
async def list_lots(
    product_id: Optional[uuid.UUID] = Query(None),
    warehouse_id: Optional[uuid.UUID] = Query(None),
    status: Optional[str] = Query(None, pattern="^(ACTIVE|DEPLETED|EXPIRED)$"),
    include_depleted: bool = Query(False),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    expiring_within_days: Optional[int] = Query(None, ge=1, le=365),
    tenant_id: Optional[uuid.UUID] = Query(None, description="SA only — filter to specific tenant"),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_read_db_session),
) -> SuccessResponse[List[LotOut]]:
    """Lot balances (lot x warehouse) with computed status."""
    tid = effective_tenant_id(user, tenant_id)
    if expiring_within_days is None:
        expiring_within_days = await get_near_expiry_days(db, tid)
    data = await get_lots(
        db,
        tid,
        product_id=product_id,
        warehouse_id=warehouse_id,
        status=status,
        include_depleted=include_depleted,
        limit=limit,
        offset=offset,
        expiring_within_days=expiring_within_days,
    )
    return SuccessResponse(data=data)


@router.get("/expiry-alerts", response_model=SuccessResponse[ExpiryAlertsOut])
@require_permission(PERMISSIONS.REPORT_EXPIRY_ALERTS)
async def expiry_alerts(
    warehouse_id: Optional[uuid.UUID] = Query(None),
    within_days: Optional[int] = Query(None, ge=1, le=365),
    tenant_id: Optional[uuid.UUID] = Query(None, description="SA only — filter to specific tenant"),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_read_db_session),
) -> SuccessResponse[ExpiryAlertsOut]:
    """Expired, expiring-soon and no-expiry lots of expiry-tracked products."""
    tid = effective_tenant_id(user, tenant_id)
    if within_days is None:
        within_days = await get_near_expiry_days(db, tid)
    data = await get_expiry_alerts(
        db, tid, warehouse_id=warehouse_id, within_days=within_days
    )
    return SuccessResponse(data=data)


# Fixed path — declared before the parameterised /{lot_id}/expiry route.
@router.get("/expiry-settings", response_model=SuccessResponse[NearExpirySettingsOut])
@require_permission(PERMISSIONS.REPORT_EXPIRY_ALERTS)
async def get_expiry_settings(
    tenant_id: Optional[uuid.UUID] = Query(None, description="SA only — filter to specific tenant"),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_read_db_session),
) -> SuccessResponse[NearExpirySettingsOut]:
    """The tenant's near-expiry window (days)."""
    tid = effective_tenant_id(user, tenant_id)
    if tid is None:
        raise HTTPException(status_code=422, detail={"code": "TENANT_ID_REQUIRED"})
    days = await get_near_expiry_days(db, tid)
    return SuccessResponse(data=NearExpirySettingsOut(near_expiry_days=days))


@router.put("/expiry-settings", response_model=SuccessResponse[NearExpirySettingsOut])
@require_permission(PERMISSIONS.TENANT_CONFIGURE)
async def put_expiry_settings(
    body: NearExpirySettingsRequest,
    tenant_id: Optional[uuid.UUID] = Query(None, description="SA only — filter to specific tenant"),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[NearExpirySettingsOut]:
    """Set the tenant's near-expiry window (TA, or SA for a chosen tenant). Audited in the same transaction."""
    tid = effective_tenant_id(user, tenant_id)
    if tid is None:
        raise HTTPException(status_code=422, detail={"code": "TENANT_ID_REQUIRED"})
    days = await set_near_expiry_days(db, str(tid), body.near_expiry_days, user)
    return SuccessResponse(data=NearExpirySettingsOut(near_expiry_days=days))


# Fixed paths — declared before the parameterised /{lot_id}/expiry route.
@router.get("/overrides", response_model=SuccessResponse[OverrideLogOut])
@require_permission(PERMISSIONS.REPORT_DISPATCH_SUMMARY)
async def list_lot_overrides(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    warehouse_id: Optional[uuid.UUID] = Query(None),
    product_id: Optional[uuid.UUID] = Query(None),
    strategy: Optional[str] = Query(None, pattern="^(FEFO|FIFO|LIFO)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    tenant_id: Optional[uuid.UUID] = Query(None, description="SA only — filter to specific tenant"),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_read_db_session),
) -> SuccessResponse[OverrideLogOut]:
    """Lot-allocation overrides in the period, newest first."""
    tid = effective_tenant_id(user, tenant_id)
    data = await list_overrides(
        db, user, tid,
        date_from=date_from, date_to=date_to, warehouse_id=warehouse_id,
        product_id=product_id, strategy=strategy, limit=limit, offset=offset,
    )
    return SuccessResponse(data=data)


@router.get("/overrides/summary", response_model=SuccessResponse[OverrideSummaryOut])
@require_permission(PERMISSIONS.REPORT_DISPATCH_SUMMARY)
async def lot_override_summary(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    warehouse_id: Optional[uuid.UUID] = Query(None),
    tenant_id: Optional[uuid.UUID] = Query(None, description="SA only — filter to specific tenant"),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_read_db_session),
) -> SuccessResponse[OverrideSummaryOut]:
    """FEFO compliance: decisions, overridden and the compliance rate."""
    tid = effective_tenant_id(user, tenant_id)
    data = await override_summary(
        db, user, tid, date_from=date_from, date_to=date_to, warehouse_id=warehouse_id
    )
    return SuccessResponse(data=data)


@router.patch("/{lot_id}/expiry", response_model=SuccessResponse[SetLotExpiryOut])
@require_permission(PERMISSIONS.PRODUCT_UPDATE)
async def patch_lot_expiry(
    lot_id: uuid.UUID,
    body: SetLotExpiryRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[SetLotExpiryOut]:
    """Set an expiry once on a lot that has none. Metadata only - no ledger write."""
    if not feature_lot_tracking_enabled():
        raise HTTPException(status_code=403, detail={"code": "FEATURE_NOT_ENABLED"})
    result = await set_lot_expiry(
        db, str(user.tenant_id), str(lot_id), body.expiry_date, user
    )
    return SuccessResponse(data=SetLotExpiryOut(**result))
