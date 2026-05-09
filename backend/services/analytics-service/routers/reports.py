from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.dependencies import get_read_db_session
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse

router = APIRouter()


@router.get("/inventory-valuation", response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.REPORT_INV_VALUATION)
async def inventory_valuation(
    user=Depends(lambda: None),
    db: AsyncSession = Depends(get_read_db_session),
) -> SuccessResponse[dict]:
    return SuccessResponse(data={"message": "Queries run on read replica"})


@router.get("/stock-movement", response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.REPORT_STOCK_MOVEMENT)
async def stock_movement(
    user=Depends(lambda: None),
    db: AsyncSession = Depends(get_read_db_session),
) -> SuccessResponse[dict]:
    return SuccessResponse(data={})


@router.get("/expiry-alerts", response_model=SuccessResponse[list])
@require_permission(PERMISSIONS.REPORT_EXPIRY_ALERTS)
async def expiry_alerts(
    user=Depends(lambda: None),
    db: AsyncSession = Depends(get_read_db_session),
) -> SuccessResponse[list]:
    return SuccessResponse(data=[])
