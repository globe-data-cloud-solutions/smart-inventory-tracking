"""Notification alerts endpoint — /api/v1/inventory/alerts."""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_current_user, get_read_db_session
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse
from shared.utils.tenant_scope import effective_tenant_id

router = APIRouter()


class AutoApprovalAlertOut(BaseModel):
    id: str
    alert_type: str = "AUTO_APPROVAL_NOTICE"
    transfer_id: str
    transfer_ref: str
    transfer_type: str
    quantity: float
    product_name: str
    warehouse_name: str
    reason: str
    created_at: str


@router.get("/", response_model=SuccessResponse[List[AutoApprovalAlertOut]])
@require_permission(PERMISSIONS.NOTIFICATION_VIEW)
async def get_notification_alerts(
    alert_type: Optional[str] = Query(None),
    tenant_id: Optional[uuid.UUID] = Query(None),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_read_db_session),
) -> SuccessResponse[List[AutoApprovalAlertOut]]:
    """Notification bell alerts. Currently supports alert_type=AUTO_APPROVAL_NOTICE."""
    if alert_type != "AUTO_APPROVAL_NOTICE":
        return SuccessResponse(data=[])

    tid = effective_tenant_id(user, tenant_id)
    rows = (
        await db.execute(
            text("""
                SELECT
                    ah.id::text                                            AS id,
                    ah.transaction_id::text                               AS transfer_id,
                    COALESCE(t.reference_number, 'N/A')                  AS transfer_ref,
                    COALESCE(t.transfer_type::text, 'PULL')              AS transfer_type,
                    COALESCE(tol.quantity, 0)::float                     AS quantity,
                    COALESCE(p.name, 'Unknown product')                  AS product_name,
                    COALESCE(n.name, 'Unknown warehouse')                AS warehouse_name,
                    COALESCE(ah.notes, 'Auto-approved within threshold') AS reason,
                    ah.actioned_at::text                                  AS created_at
                FROM approval_history ah
                LEFT JOIN transfer_orders t
                       ON t.id = ah.transaction_id
                LEFT JOIN LATERAL (
                    SELECT product_id, quantity
                    FROM transfer_order_lines
                    WHERE transfer_order_id = t.id
                    ORDER BY created_at
                    LIMIT 1
                ) tol ON true
                LEFT JOIN products p
                       ON p.id = tol.product_id AND p.tenant_id = ah.tenant_id
                LEFT JOIN organization_node n
                       ON n.id = t.from_warehouse_id
                WHERE ah.tenant_id = :tid
                  AND ah.action   = 'AUTO_APPROVED'
                  AND ah.actioned_at > now() - interval '24 hours'
                ORDER BY ah.actioned_at DESC
                LIMIT 50
            """),
            {"tid": str(tid)},
        )
    ).fetchall()

    return SuccessResponse(
        data=[
            AutoApprovalAlertOut(
                id=r.id,
                transfer_id=r.transfer_id,
                transfer_ref=r.transfer_ref,
                transfer_type=r.transfer_type,
                quantity=r.quantity,
                product_name=r.product_name,
                warehouse_name=r.warehouse_name,
                reason=r.reason,
                created_at=r.created_at,
            )
            for r in rows
        ]
    )
