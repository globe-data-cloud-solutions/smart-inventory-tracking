from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_db_session
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse
from schemas.inventory import ReceiveStockRequest, ReceiveStockResponse
from services.inventory_service import InventoryService
from dependencies import get_current_user

router = APIRouter()


@router.post("/", status_code=201, response_model=SuccessResponse[ReceiveStockResponse])
@require_permission(PERMISSIONS.INVENTORY_RECEIVE)
async def receive_stock(
    body: ReceiveStockRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[ReceiveStockResponse]:
    svc = InventoryService(db)
    result = await svc.receive(user, body)
    return SuccessResponse(data=result)
