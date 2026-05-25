from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_db_session
from dependencies import get_current_user
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse
from schemas.inventory import AdjustmentListItem, AdjustmentRequest, AdjustmentResponse
from services.inventory_service import InventoryService

router = APIRouter()


@router.get("/", response_model=SuccessResponse[List[AdjustmentListItem]])
@require_permission(PERMISSIONS.ADJUSTMENT_LIST)
async def list_adjustments(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[List[AdjustmentListItem]]:
    svc = InventoryService(db)
    result = await svc.list_adjustments(user, page=page, limit=limit)
    return SuccessResponse(data=result)


@router.post("/", status_code=201, response_model=SuccessResponse[AdjustmentResponse])
@require_permission(PERMISSIONS.ADJUSTMENT_CREATE)
async def create_adjustment(
    body: AdjustmentRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[AdjustmentResponse]:
    svc = InventoryService(db)
    result = await svc.create_adjustment(user, body)
    return SuccessResponse(data=result)


@router.post("/{adjustment_id}/approve", response_model=SuccessResponse[AdjustmentResponse])
@require_permission(PERMISSIONS.ADJUSTMENT_APPROVE)
async def approve_adjustment(
    adjustment_id: UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[AdjustmentResponse]:
    svc = InventoryService(db)
    result = await svc.transition_adjustment(user, adjustment_id, "APPROVED")
    return SuccessResponse(data=result)
