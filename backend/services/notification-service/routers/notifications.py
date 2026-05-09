from fastapi import APIRouter, Depends

from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse

router = APIRouter()


@router.get("/", response_model=SuccessResponse[list])
@require_permission(PERMISSIONS.NOTIFICATION_VIEW)
async def list_notifications(user=Depends(lambda: None)) -> SuccessResponse[list]:
    return SuccessResponse(data=[])
