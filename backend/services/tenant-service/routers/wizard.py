import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.dependencies import get_db_session
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse
from services.tenant_service.schemas.tenant import WizardData, WizardResult
from services.tenant_service.services.wizard_service import complete_wizard

router = APIRouter()


@router.post("/{tenant_id}/wizard", response_model=SuccessResponse[WizardResult])
@require_permission(PERMISSIONS.TENANT_CONFIGURE)
async def run_wizard(
    tenant_id: uuid.UUID,
    body: WizardData,
    user=Depends(lambda: None),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[WizardResult]:
    result = await complete_wizard(db, str(tenant_id), body, str(user.user_id))
    return SuccessResponse(data=result)
