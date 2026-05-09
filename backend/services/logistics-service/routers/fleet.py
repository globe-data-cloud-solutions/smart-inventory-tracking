from fastapi import APIRouter, Depends
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse

router = APIRouter()


@router.get("/fleet", response_model=SuccessResponse[list])
@require_permission(PERMISSIONS.LOGISTICS_FLEET_MANAGE)
async def list_fleet(user=Depends(lambda: None)) -> SuccessResponse[list]:
    return SuccessResponse(data=[])


@router.get("/routes", response_model=SuccessResponse[list])
@require_permission(PERMISSIONS.LOGISTICS_ROUTE_VIEW)
async def list_routes(user=Depends(lambda: None)) -> SuccessResponse[list]:
    return SuccessResponse(data=[])
