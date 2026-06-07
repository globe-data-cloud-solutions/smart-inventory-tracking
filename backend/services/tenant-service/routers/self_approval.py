"""Self-approval policy endpoints.

GET  /tenants/{tenant_id}/self-approval-policies
PUT  /tenants/{tenant_id}/self-approval-policies
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


class SelfApprovalPolicyIn(BaseModel):
    role_code: str
    level_number: int
    transfer_types: List[str] = ["PULL", "PUSH", "SISTER"]
    threshold_type: str = "QUANTITY"
    qty_limit: Optional[Decimal] = None
    value_limit: Optional[Decimal] = None
    is_active: bool = True


class SelfApprovalPolicyOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    role_code: str
    level_number: int
    transfer_types: List[str]
    threshold_type: str
    qty_limit: Optional[Decimal]
    value_limit: Optional[Decimal]
    is_active: bool


@router.get("/{tenant_id}/self-approval-policies",
            response_model=SuccessResponse[List[SelfApprovalPolicyOut]])
@require_permission(PERMISSIONS.SELF_APPROVAL_POLICY_VIEW)
async def list_self_approval_policies(
    tenant_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[List[SelfApprovalPolicyOut]]:
    rows = (await db.execute(
        text("""
            SELECT id, tenant_id, role_code, level_number,
                   transfer_types, threshold_type, qty_limit, value_limit, is_active
            FROM   self_approval_policies
            WHERE  tenant_id = :tid
            ORDER  BY level_number, role_code
        """),
        {"tid": str(tenant_id)},
    )).fetchall()

    return SuccessResponse(data=[
        SelfApprovalPolicyOut(
            id=r.id, tenant_id=r.tenant_id,
            role_code=r.role_code, level_number=r.level_number,
            transfer_types=list(r.transfer_types), threshold_type=r.threshold_type,
            qty_limit=r.qty_limit, value_limit=r.value_limit, is_active=r.is_active,
        )
        for r in rows
    ])


@router.put("/{tenant_id}/self-approval-policies",
            response_model=SuccessResponse[List[SelfApprovalPolicyOut]])
@require_permission(PERMISSIONS.SELF_APPROVAL_POLICY_MANAGE)
async def upsert_self_approval_policies(
    tenant_id: uuid.UUID,
    body: List[SelfApprovalPolicyIn],
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[List[SelfApprovalPolicyOut]]:
    tid = str(tenant_id)
    upserted: list[SelfApprovalPolicyOut] = []

    for policy in body:
        row = (await db.execute(
            text("""
                INSERT INTO self_approval_policies
                    (tenant_id, role_code, level_number, transfer_types,
                     threshold_type, qty_limit, value_limit, is_active)
                VALUES
                    (:tid, :role, :level, CAST(:types AS text[]),
                     :threshold, :qty, :val, :active)
                ON CONFLICT (tenant_id, role_code, level_number) DO UPDATE SET
                    transfer_types = EXCLUDED.transfer_types,
                    threshold_type = EXCLUDED.threshold_type,
                    qty_limit      = EXCLUDED.qty_limit,
                    value_limit    = EXCLUDED.value_limit,
                    is_active      = EXCLUDED.is_active,
                    updated_at     = NOW()
                RETURNING id, tenant_id, role_code, level_number,
                          transfer_types, threshold_type, qty_limit, value_limit, is_active
            """),
            {
                "tid":       tid,
                "role":      policy.role_code,
                "level":     policy.level_number,
                "types":     list(policy.transfer_types),
                "threshold": policy.threshold_type,
                "qty":       float(policy.qty_limit) if policy.qty_limit is not None else None,
                "val":       float(policy.value_limit) if policy.value_limit is not None else None,
                "active":    policy.is_active,
            },
        )).fetchone()

        if row:
            upserted.append(SelfApprovalPolicyOut(
                id=row.id, tenant_id=row.tenant_id,
                role_code=row.role_code, level_number=row.level_number,
                transfer_types=list(row.transfer_types), threshold_type=row.threshold_type,
                qty_limit=row.qty_limit, value_limit=row.value_limit, is_active=row.is_active,
            ))

    return SuccessResponse(data=upserted)
