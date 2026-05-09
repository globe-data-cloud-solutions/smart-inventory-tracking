import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.dependencies import get_db_session
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse

router = APIRouter()


@router.get("/", response_model=SuccessResponse[list])
@require_permission(PERMISSIONS.PRODUCT_LIST)
async def list_products(
    q: Optional[str] = Query(None, description="SKU / name search — uses pg_trgm"),
    user=Depends(lambda: None),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[list]:
    if q:
        result = await db.execute(
            text(
                "SELECT id, sku, name FROM products "
                "WHERE tenant_id = :tid AND name % :q AND is_active = true "
                "ORDER BY similarity(name, :q) DESC LIMIT 50"
            ),
            {"tid": str(user.tenant_id), "q": q},
        )
    else:
        result = await db.execute(
            text("SELECT id, sku, name FROM products WHERE tenant_id = :tid AND is_active = true LIMIT 100"),
            {"tid": str(user.tenant_id)},
        )
    rows = result.fetchall()
    return SuccessResponse(data=[{"id": str(r.id), "sku": r.sku, "name": r.name} for r in rows])


@router.post("/", status_code=201, response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.PRODUCT_CREATE)
async def create_product(
    user=Depends(lambda: None),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[dict]:
    return SuccessResponse(data={"message": "product created"})
