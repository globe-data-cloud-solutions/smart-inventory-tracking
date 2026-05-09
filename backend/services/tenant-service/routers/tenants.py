import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.dependencies import get_db_session
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse
from services.tenant_service.schemas.tenant import TenantCreateRequest, TenantResponse

router = APIRouter()


@router.post("/", status_code=201, response_model=SuccessResponse[TenantResponse])
@require_permission(PERMISSIONS.TENANT_CREATE)
async def create_tenant(
    body: TenantCreateRequest,
    user=Depends(lambda: None),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TenantResponse]:
    from sqlalchemy import text
    tenant_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO tenants (id, name, plan_id, default_locale) "
            "VALUES (:id, :name, :plan_id, :locale)"
        ),
        {
            "id": str(tenant_id),
            "name": body.name,
            "plan_id": str(body.plan_id),
            "locale": body.default_locale,
        },
    )
    return SuccessResponse(
        data=TenantResponse(
            id=tenant_id,
            name=body.name,
            organisation_type=None,
            onboarding_complete=False,
            default_locale=body.default_locale,
            is_active=True,
        )
    )


@router.get("/{tenant_id}", response_model=SuccessResponse[TenantResponse])
@require_permission(PERMISSIONS.TENANT_VIEW)
async def get_tenant(
    tenant_id: uuid.UUID,
    user=Depends(lambda: None),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TenantResponse]:
    from fastapi import HTTPException
    from sqlalchemy import text
    result = await db.execute(
        text("SELECT * FROM tenants WHERE id = :id"), {"id": str(tenant_id)}
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return SuccessResponse(
        data=TenantResponse(
            id=row.id,
            name=row.name,
            organisation_type=row.organisation_type,
            onboarding_complete=row.onboarding_complete,
            default_locale=row.default_locale,
            is_active=row.is_active,
        )
    )
