from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.dependencies import get_db_session
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse
from schemas.inventory import AdjustmentRequest, AdjustmentResponse
from services.inventory_service import InventoryService

router = APIRouter()


@router.post("/", status_code=201, response_model=SuccessResponse[AdjustmentResponse])
@require_permission(PERMISSIONS.ADJUSTMENT_CREATE)
async def create_adjustment(
    body: AdjustmentRequest,
    user=Depends(lambda: None),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[AdjustmentResponse]:
    svc = InventoryService(db)
    result = await svc.create_adjustment(user, body)
    return SuccessResponse(data=result)


@router.post("/{adjustment_id}/approve", response_model=SuccessResponse[AdjustmentResponse])
@require_permission(PERMISSIONS.ADJUSTMENT_APPROVE)
async def approve_adjustment(
    adjustment_id: UUID,
    user=Depends(lambda: None),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[AdjustmentResponse]:
    svc = InventoryService(db)
    result = await svc.transition_adjustment(user, adjustment_id, "APPROVED")
    return SuccessResponse(data=result)
