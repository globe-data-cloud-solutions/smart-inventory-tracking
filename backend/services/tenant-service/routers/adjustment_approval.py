"""Adjustment approval rules API.

GET /tenants/{tenant_id}/adjustment-approval-rules
PUT /tenants/{tenant_id}/adjustment-approval-rules
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_current_user, get_db_session_for_tenant
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse

router = APIRouter()


class AdjApprovalRuleIn(BaseModel):
    role_code: str
    level_number: int
    mode: str = "GLOBAL"
    reason_code: Optional[str] = None
    threshold_type: str = "QUANTITY"
    qty_limit: Optional[Decimal] = None
    value_limit: Optional[Decimal] = None
    approver_role_code: Optional[str] = None
    approver_position_id: Optional[uuid.UUID] = None
    priority: int = 10
    is_active: bool = True


class AdjApprovalRuleOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    role_code: str
    level_number: int
    mode: str
    reason_code: Optional[str]
    threshold_type: str
    qty_limit: Optional[Decimal]
    value_limit: Optional[Decimal]
    approver_role_code: Optional[str]
    approver_position_id: Optional[uuid.UUID]
    approver_position_title: Optional[str] = None
    priority: int
    is_active: bool


@router.get("/{tenant_id}/adjustment-approval-rules",
            response_model=SuccessResponse[List[AdjApprovalRuleOut]])
@require_permission(PERMISSIONS.ADJUSTMENT_APPROVAL_RULE_VIEW)
async def list_adj_approval_rules(
    tenant_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[List[AdjApprovalRuleOut]]:
    rows = (await db.execute(
        text("""
            SELECT r.id, r.tenant_id, r.role_code, r.level_number, r.mode,
                   r.reason_code, r.threshold_type, r.qty_limit, r.value_limit,
                   r.approver_role_code, r.approver_position_id, p.title AS approver_position_title,
                   r.priority, r.is_active
            FROM   adjustment_approval_rules r
            LEFT JOIN positions p ON p.id = r.approver_position_id
            WHERE  r.tenant_id = :tid
            ORDER  BY r.role_code, r.level_number, r.priority
        """),
        {"tid": str(tenant_id)},
    )).fetchall()

    return SuccessResponse(data=[
        AdjApprovalRuleOut(
            id=r.id, tenant_id=r.tenant_id,
            role_code=r.role_code, level_number=r.level_number,
            mode=r.mode, reason_code=r.reason_code,
            threshold_type=r.threshold_type,
            qty_limit=r.qty_limit, value_limit=r.value_limit,
            approver_role_code=r.approver_role_code,
            approver_position_id=r.approver_position_id,
            approver_position_title=r.approver_position_title,
            priority=r.priority, is_active=r.is_active,
        )
        for r in rows
    ])


@router.put("/{tenant_id}/adjustment-approval-rules",
            response_model=SuccessResponse[List[AdjApprovalRuleOut]])
@require_permission(PERMISSIONS.ADJUSTMENT_APPROVAL_RULE_MANAGE)
async def upsert_adj_approval_rules(
    tenant_id: uuid.UUID,
    body: List[AdjApprovalRuleIn],
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[List[AdjApprovalRuleOut]]:
    tid = str(tenant_id)
    await db.execute(
        text("DELETE FROM adjustment_approval_rules WHERE tenant_id = :tid"),
        {"tid": tid},
    )
    for rule in body:
        await db.execute(
            text("""
                INSERT INTO adjustment_approval_rules
                    (tenant_id, role_code, level_number, mode, reason_code,
                     threshold_type, qty_limit, value_limit,
                     approver_role_code, approver_position_id, priority, is_active)
                VALUES
                    (:tid, :role, :level, :mode, :rc,
                     :tt, :qty, :val,
                     :arc, :apid, :prio, :ia)
            """),
            {
                "tid":  tid,
                "role": rule.role_code,
                "level": rule.level_number,
                "mode": rule.mode,
                "rc":   rule.reason_code,
                "tt":   rule.threshold_type,
                "qty":  float(rule.qty_limit) if rule.qty_limit is not None else None,
                "val":  float(rule.value_limit) if rule.value_limit is not None else None,
                "arc":  rule.approver_role_code,
                "apid": str(rule.approver_position_id) if rule.approver_position_id else None,
                "prio": rule.priority,
                "ia":   rule.is_active,
            },
        )
    return await list_adj_approval_rules(tenant_id=tenant_id, user=user, db=db)
