from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.dependencies import get_read_db_session
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse

router = APIRouter()


@router.get("/", response_model=SuccessResponse[list])
@require_permission(PERMISSIONS.AI_FORECAST_VIEW)
async def list_forecasts(
    user=Depends(lambda: None),
    db: AsyncSession = Depends(get_read_db_session),
) -> SuccessResponse[list]:
    """AI recommendations always start with status=PENDING_APPROVAL and never auto-execute."""
    return SuccessResponse(data=[])


@router.post("/run")
@require_permission(PERMISSIONS.AI_MODEL_RUN)
async def run_model(user=Depends(lambda: None)) -> dict:
    """SYS role only — any user role call returns HTTP 403."""
    return {"status": "queued"}
