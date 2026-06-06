from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_db_session, get_current_user
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse
from schemas.inventory import AuditLogItem

router = APIRouter()


@router.get("/", response_model=SuccessResponse[List[AuditLogItem]])
@require_permission(PERMISSIONS.AUDIT_VIEW_LOGS)
async def list_audit_logs(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    action: str = Query(None),
    resource_type: str = Query(None),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[List[AuditLogItem]]:
    filters = ["tenant_id = :tid"]
    params: dict = {"tid": str(user.tenant_id), "limit": limit, "offset": (page - 1) * limit}

    if action:
        filters.append("action = :action")
        params["action"] = action
    if resource_type:
        filters.append("resource_type = :rtype")
        params["rtype"] = resource_type

    where = " AND ".join(filters)
    rows = (await db.execute(
        text(
            f"SELECT id, timestamp, user_id, role, action, resource_type, "
            f"       resource_id, decision, reason, abac_context "
            f"FROM audit_logs "
            f"WHERE {where} "
            f"ORDER BY timestamp DESC "
            f"LIMIT :limit OFFSET :offset"
        ),
        params,
    )).fetchall()

    return SuccessResponse(data=[
        AuditLogItem(
            id=r.id,
            timestamp=r.timestamp,
            user_id=r.user_id,
            role=r.role,
            action=r.action,
            resource_type=r.resource_type,
            resource_id=r.resource_id,
            decision=r.decision,
            reason=r.reason,
            abac_context=r.abac_context,
        )
        for r in rows
    ])
