from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.dependencies import get_db_session
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.idempotency import idempotency_key_exists
from shared.utils.responses import SuccessResponse

router = APIRouter()


class OfflineSyncItem(BaseModel):
    idempotency_key: str
    action: str
    payload: dict


class SyncResult(BaseModel):
    idempotency_key: str
    status: str  # SYNCED | CONFLICT | ERROR
    detail: str = ""


@router.post("/batch", response_model=SuccessResponse[List[SyncResult]])
@require_permission(PERMISSIONS.SYNC_QUEUE_VIEW)
async def sync_batch(
    items: List[OfflineSyncItem],
    user=Depends(lambda: None),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[List[SyncResult]]:
    results = []
    for item in items:
        if await idempotency_key_exists(db, item.idempotency_key):
            results.append(SyncResult(
                idempotency_key=item.idempotency_key,
                status="SYNCED",
                detail="Already processed",
            ))
        else:
            results.append(SyncResult(
                idempotency_key=item.idempotency_key,
                status="SYNCED",
            ))
    return SuccessResponse(data=results)
