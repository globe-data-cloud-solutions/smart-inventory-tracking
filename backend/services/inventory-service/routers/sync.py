"""Offline queue drain — POST /api/v1/inventory/sync/batch (RB-10).

The browser queues Receive and Issue movements in IndexedDB while offline and
sends them here on reconnect. Each item is posted through the SAME service
method the online screens use (InventoryService.receive / issue_stock), with
the logged-in user, so permissions, scope, RLS, validation and the ledger rules
are identical to an online post. Nothing here writes the ledger directly.

Per item the result is:
- SYNCED   posted now, or already posted earlier (409 DUPLICATE_TRANSACTION on
           receive, or the same key replayed on issue). Safe to remove from the
           device queue. A duplicate is success: the response to the first
           attempt was lost, not the stock movement.
- CONFLICT a business rule rejected it (for example insufficient stock at sync
           time, or an inactive warehouse). The device keeps the item and shows
           the reason so the user can retry or discard it.
- ERROR    not posted, may succeed later (unknown action, invalid payload,
           server error). The device keeps the item as PENDING.

Each item runs in its own savepoint, so one failed item does not undo the
others. The session commits once at the end of the request.
"""

from __future__ import annotations

import logging
from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_current_user, get_db_session
from schemas.inventory import IssueStockRequest, ReceiveStockRequest
from services.inventory_service import InventoryService
from shared.permissions.middleware import check_permission, require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_ITEMS_PER_BATCH = 200

# action -> (permission checked per item, request model, service method name)
SYNC_ACTIONS: dict[str, tuple[Any, type[BaseModel], str]] = {
    "inventory:receive": (PERMISSIONS.INVENTORY_RECEIVE, ReceiveStockRequest, "receive"),
    "inventory:issue": (PERMISSIONS.INVENTORY_ISSUE, IssueStockRequest, "issue_stock"),
}


class SyncItem(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=200)
    action: str = Field(min_length=1, max_length=100)
    payload: dict[str, Any]


class SyncBatchRequest(BaseModel):
    items: List[SyncItem] = Field(max_length=MAX_ITEMS_PER_BATCH)


class SyncResult(BaseModel):
    idempotency_key: str
    status: str  # SYNCED | CONFLICT | ERROR
    code: str | None = None
    detail: str = ""


def _error_code(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, dict) and isinstance(detail.get("code"), str):
        return detail["code"]
    return "REJECTED"


@router.post("/batch", response_model=SuccessResponse[List[SyncResult]])
@require_permission(PERMISSIONS.INVENTORY_RECEIVE)
async def sync_batch(
    body: SyncBatchRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[List[SyncResult]]:
    svc = InventoryService(db)
    tid = str(user.tenant_id)
    results: list[SyncResult] = []

    for item in body.items:
        key = item.idempotency_key
        spec = SYNC_ACTIONS.get(item.action)
        if spec is None:
            results.append(SyncResult(idempotency_key=key, status="ERROR", code="UNKNOWN_ACTION"))
            continue

        permission, model, method_name = spec
        allowed = (await check_permission(user, permission, {"tenant_id": tid}, db=db)).allowed
        if not allowed:
            results.append(SyncResult(idempotency_key=key, status="CONFLICT", code="FORBIDDEN"))
            continue

        try:
            request = model.model_validate({**item.payload, "idempotency_key": key})
        except ValidationError as exc:
            results.append(
                SyncResult(
                    idempotency_key=key,
                    status="ERROR",
                    code="INVALID_PAYLOAD",
                    detail=str(exc.errors()[0].get("msg", ""))[:200],
                )
            )
            continue

        try:
            async with db.begin_nested():
                await getattr(svc, method_name)(user, request)
            results.append(SyncResult(idempotency_key=key, status="SYNCED"))
        except HTTPException as exc:
            code = _error_code(exc)
            if code == "DUPLICATE_TRANSACTION":
                results.append(
                    SyncResult(idempotency_key=key, status="SYNCED", detail="Already posted")
                )
            elif 400 <= exc.status_code < 500:
                results.append(SyncResult(idempotency_key=key, status="CONFLICT", code=code))
            else:
                logger.exception("sync item failed: %s", key)
                results.append(SyncResult(idempotency_key=key, status="ERROR", code="SERVER_ERROR"))
        except Exception:
            logger.exception("sync item failed: %s", key)
            results.append(SyncResult(idempotency_key=key, status="ERROR", code="SERVER_ERROR"))

    return SuccessResponse(data=results)
