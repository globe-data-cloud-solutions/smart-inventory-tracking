"""Lot read endpoint — /api/v1/inventory/lots.

Scoping mirrors GET /analytics/stock exactly: same permission
(inventory:view_balance) and the same warehouse_id-kwarg ABAC path through
require_permission -> check_permission (get_descendant_node_ids traversal
for FACILITY_SCOPED roles) in shared/permissions/middleware.py. No raw
warehouse_id equality check is added here.
"""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_current_user, get_read_db_session
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse
from shared.utils.tenant_scope import effective_tenant_id
from schemas.analytics import LotOut
from services.inventory_analytics import get_lots

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
    tenant_id: Optional[uuid.UUID] = Query(None, description="SA only — filter to specific tenant"),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_read_db_session),
) -> SuccessResponse[List[LotOut]]:
    """Lot balances (lot x warehouse) with computed status."""
    tid = effective_tenant_id(user, tenant_id)
    data = await get_lots(
        db,
        tid,
        product_id=product_id,
        warehouse_id=warehouse_id,
        status=status,
        include_depleted=include_depleted,
        limit=limit,
        offset=offset,
    )
    return SuccessResponse(data=data)
