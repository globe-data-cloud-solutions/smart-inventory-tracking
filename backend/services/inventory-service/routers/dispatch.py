"""Dispatch allocation preview — /api/v1/inventory/dispatch.

Read-only: shows which lots the dispatch engine WOULD draw from for a
quantity. Nothing is locked, reserved or written.

Scoping mirrors GET /lots exactly: same permission (inventory:view_balance)
and the same warehouse_id-kwarg ABAC path through require_permission ->
check_permission (get_descendant_node_ids traversal for FACILITY_SCOPED
roles) in shared/permissions/middleware.py. No raw warehouse_id equality
check is added here.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_current_user, get_read_db_session
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse
from shared.utils.tenant_scope import effective_tenant_id
from schemas.inventory import AllocationLineOut, DispatchPreviewResponse
from services.dispatch_service import (
    load_candidate_lots,
    load_product,
    plan_allocation,
    resolve_strategy,
)

router = APIRouter()


@router.get("/preview", response_model=SuccessResponse[DispatchPreviewResponse])
@require_permission(PERMISSIONS.INVENTORY_VIEW_BALANCE)
async def preview_allocation(
    product_id: uuid.UUID = Query(...),
    warehouse_id: uuid.UUID = Query(...),
    quantity: Decimal = Query(..., gt=0),
    tenant_id: Optional[uuid.UUID] = Query(None, description="SA only — filter to specific tenant"),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_read_db_session),
) -> SuccessResponse[DispatchPreviewResponse]:
    """Suggested lot allocation for a quantity, in the product's dispatch order."""
    tid = effective_tenant_id(user, tenant_id)
    product = await load_product(db, tid, product_id)
    strategy, source = resolve_strategy(
        product.batch_tracking, product.expiry_tracking, product.dispatch_strategy
    )

    if strategy is None:
        return SuccessResponse(
            data=DispatchPreviewResponse(
                product_id=product_id,
                warehouse_id=warehouse_id,
                quantity=quantity,
                strategy=None,
                strategy_source=source,
                lines=[],
                shortfall=quantity,
                expired_skipped=[],
                available_total=Decimal("0"),
            )
        )

    lots = await load_candidate_lots(db, tid, product_id, warehouse_id)
    plan = plan_allocation(lots, quantity, strategy)
    expired_ids = {line.lot_id for line in plan.expired_skipped}
    available_total = sum(
        (lot.quantity for lot in lots if lot.lot_id not in expired_ids), Decimal("0")
    )

    return SuccessResponse(
        data=DispatchPreviewResponse(
            product_id=product_id,
            warehouse_id=warehouse_id,
            quantity=quantity,
            strategy=strategy,
            strategy_source=source,
            lines=[AllocationLineOut(**vars(line)) for line in plan.lines],
            shortfall=plan.shortfall,
            expired_skipped=[AllocationLineOut(**vars(line)) for line in plan.expired_skipped],
            available_total=available_total,
        )
    )
