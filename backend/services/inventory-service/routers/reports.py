"""Reports — /api/v1/inventory/reports (2026-10-22).

Scope: every report is limited to the caller's level (resolve_node_scope):
TA / NM / SA / AU see the tenant; WM, LM, SA_GT, RT and RM see their own node
and everything below it. A facility-scoped caller with no node sees nothing.
Reads run on the read replica (get_read_db_session). The tenant is resolved the
same way as the session's RLS context (_rls_tenant_for): an SA scopes a request
with ?tenant_id=<uuid>, everyone else gets their token's tenant.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import _rls_tenant_for, get_current_user, get_read_db_session
from schemas.reports import ExpiryAlertRow, MovementRow, ReportFilterOptions, ValuationRow
from services.report_filters import filter_options, filter_scope, intersect_scopes
from services.report_queries import get_expiry_alerts, get_inventory_valuation, get_stock_movement
from shared.permissions.hierarchy_service import resolve_node_scope
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse

router = APIRouter()


def _parse_day(value: Optional[str], name: str) -> Optional[date]:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail={"code": "INVALID_DATE", "field": name}
        ) from exc


def _report_tenant(user, request: Request) -> uuid.UUID:
    """The tenant this report is for; 422 TENANT_REQUIRED when there is none.

    An SA token carries no tenant, so without ?tenant_id=<uuid> there is nothing
    to report on.
    """
    tenant = _rls_tenant_for(user, request)
    if not tenant:
        raise HTTPException(status_code=422, detail={"code": "TENANT_REQUIRED"})
    return uuid.UUID(str(tenant))


async def _report_scope(
    db: AsyncSession,
    user,
    tenant_id: uuid.UUID,
    level: Optional[int],
    node_id: Optional[str],
    warehouse_id: Optional[str],
) -> Optional[set[str]]:
    """The caller's level scope, narrowed by the optional filters."""
    caller = await resolve_node_scope(db, user)
    chosen = await filter_scope(db, str(tenant_id), level, node_id, warehouse_id)
    return intersect_scopes(caller, chosen)


_FILTER_QUERY_DOC = (
    "Optional filters, each narrowing the caller's own scope: level (the tenant's "
    "level number, requires node_id), node_id (that node and everything below it), "
    "warehouse_id (one warehouse)."
)


@router.get("/filter-options", response_model=SuccessResponse[ReportFilterOptions])
@require_permission(PERMISSIONS.REPORT_FILTER_OPTIONS)
async def report_filter_options(
    request: Request,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_read_db_session),
) -> SuccessResponse[ReportFilterOptions]:
    tenant_id = _report_tenant(user, request)
    scope = await resolve_node_scope(db, user)
    data = await filter_options(db, str(tenant_id), scope)
    return SuccessResponse(data=data)


@router.get("/inventory-valuation", response_model=SuccessResponse[list[ValuationRow]])
@require_permission(PERMISSIONS.REPORT_INV_VALUATION)
async def inventory_valuation(
    request: Request,
    level: Optional[int] = Query(None, ge=1, le=5, description=_FILTER_QUERY_DOC),
    node_id: Optional[str] = Query(None),
    warehouse_id: Optional[str] = Query(None),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_read_db_session),
) -> SuccessResponse[list[ValuationRow]]:
    tenant_id = _report_tenant(user, request)
    scope = await _report_scope(db, user, tenant_id, level, node_id, warehouse_id)
    data = await get_inventory_valuation(db, tenant_id, scope)
    return SuccessResponse(data=data)


@router.get("/stock-movement", response_model=SuccessResponse[list[MovementRow]])
@require_permission(PERMISSIONS.REPORT_STOCK_MOVEMENT)
async def stock_movement(
    request: Request,
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD; default 30 days back"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD; default today"),
    level: Optional[int] = Query(None, ge=1, le=5, description=_FILTER_QUERY_DOC),
    node_id: Optional[str] = Query(None),
    warehouse_id: Optional[str] = Query(None),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_read_db_session),
) -> SuccessResponse[list[MovementRow]]:
    tenant_id = _report_tenant(user, request)
    scope = await _report_scope(db, user, tenant_id, level, node_id, warehouse_id)
    data = await get_stock_movement(
        db,
        tenant_id,
        scope,
        date_from=_parse_day(date_from, "date_from"),
        date_to=_parse_day(date_to, "date_to"),
    )
    return SuccessResponse(data=data)


@router.get("/expiry-alerts", response_model=SuccessResponse[list[ExpiryAlertRow]])
@require_permission(PERMISSIONS.REPORT_EXPIRY_ALERTS)
async def expiry_alerts(
    request: Request,
    window_days: int = Query(30, ge=1, le=365),
    level: Optional[int] = Query(None, ge=1, le=5, description=_FILTER_QUERY_DOC),
    node_id: Optional[str] = Query(None),
    warehouse_id: Optional[str] = Query(None),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_read_db_session),
) -> SuccessResponse[list[ExpiryAlertRow]]:
    tenant_id = _report_tenant(user, request)
    scope = await _report_scope(db, user, tenant_id, level, node_id, warehouse_id)
    data = await get_expiry_alerts(db, tenant_id, scope, window_days=window_days)
    return SuccessResponse(data=data)
