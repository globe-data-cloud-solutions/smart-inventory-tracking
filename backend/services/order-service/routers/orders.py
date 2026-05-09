from fastapi import APIRouter, Depends
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse

router = APIRouter()


@router.get("/", response_model=SuccessResponse[list])
@require_permission(PERMISSIONS.ORDER_LIST)
async def list_orders(user=Depends(lambda: None)) -> SuccessResponse[list]:
    return SuccessResponse(data=[])


@router.post("/", status_code=201, response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.ORDER_CREATE)
async def create_order(user=Depends(lambda: None)) -> SuccessResponse[dict]:
    return SuccessResponse(data={"message": "order created"})
