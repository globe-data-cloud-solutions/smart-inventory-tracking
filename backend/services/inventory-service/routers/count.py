from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.dependencies import get_db_session
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse
from schemas.inventory import CountSessionRequest, CountSessionResponse
from services.inventory_service import InventoryService

router = APIRouter()


@router.post("/", status_code=201, response_model=SuccessResponse[CountSessionResponse])
@require_permission(PERMISSIONS.COUNT_CREATE_SESSION)
async def create_count_session(
    body: CountSessionRequest,
    user=Depends(lambda: None),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[CountSessionResponse]:
    svc = InventoryService(db)
    result = await svc.create_count_session(user, body)
    return SuccessResponse(data=result)


@router.get("/{session_id}", response_model=SuccessResponse[CountSessionResponse])
@require_permission(PERMISSIONS.COUNT_VIEW)
async def get_count_session(
    session_id: UUID,
    user=Depends(lambda: None),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[CountSessionResponse]:
    svc = InventoryService(db)
    result = await svc.get_count_session(user, session_id)
    return SuccessResponse(data=result)
