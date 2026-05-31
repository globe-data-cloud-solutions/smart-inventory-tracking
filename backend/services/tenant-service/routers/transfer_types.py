"""Transfer type configuration and approval rules API.

Transfer Type Config:
  GET  /tenants/{tenant_id}/transfer-types
  PUT  /tenants/{tenant_id}/transfer-types

Transfer Approval Rules:
  GET  /tenants/{tenant_id}/transfer-approval-rules
  PUT  /tenants/{tenant_id}/transfer-approval-rules
"""
from __future__ import annotations

import uuid
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import bindparam, text, types
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_current_user, get_db_session_for_tenant
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse

router = APIRouter()

UNDERLYING_TYPES = frozenset({"PULL", "PUSH", "SISTER"})
THRESHOLD_TYPES  = frozenset({"QUANTITY", "VALUE", "EITHER", "BOTH"})


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class LevelPermissionIn(BaseModel):
    level_number: int
    can_initiate: bool = False
    can_receive:  bool = True


class LevelPermissionOut(BaseModel):
    level_number: int
    level_name:   Optional[str]
    can_initiate: bool
    can_receive:  bool


class TransferTypeConfigIn(BaseModel):
    underlying_type: str
    display_name:    str
    description:     Optional[str]  = None
    is_active:       bool = True
    sort_order:      int  = 0
    level_permissions: List[LevelPermissionIn] = []


class TransferTypeConfigOut(BaseModel):
    id:              uuid.UUID
    underlying_type: str
    display_name:    str
    description:     Optional[str]
    is_active:       bool
    sort_order:      int
    level_permissions: List[LevelPermissionOut]


class ApprovalStepIn(BaseModel):
    sequence:       int
    position_title: Optional[str] = None
    resolution:     str = "ANY"
    execution_mode: str = "SEQUENTIAL"
    sla_hours:      Optional[int] = None


class ApprovalStepOut(BaseModel):
    sequence:       int
    position_title: Optional[str]
    resolution:     str
    execution_mode: str
    sla_hours:      Optional[int]


class ApprovalRuleIn(BaseModel):
    transfer_type_config_id: uuid.UUID
    source_level:            Optional[int]  = None
    destination_level:       Optional[int]  = None
    source_node_id:          Optional[uuid.UUID] = None
    destination_node_id:     Optional[uuid.UUID] = None
    quantity_min:            float = 0
    quantity_max:            Optional[float] = None
    value_min:               float = 0
    value_max:               Optional[float] = None
    threshold_type:          str = "QUANTITY"
    currency:                str = "ETB"
    approval_steps:          List[ApprovalStepIn] = []
    priority:                int = 0
    is_active:               bool = True


class ApprovalRuleOut(BaseModel):
    id:                      uuid.UUID
    transfer_type_config_id: uuid.UUID
    transfer_type_name:      Optional[str]
    source_level:            Optional[int]
    destination_level:       Optional[int]
    source_level_name:       Optional[str]
    dest_level_name:         Optional[str]
    quantity_min:            float
    quantity_max:            Optional[float]
    value_min:               float
    value_max:               Optional[float]
    threshold_type:          str
    currency:                Optional[str]
    approval_steps:          List[ApprovalStepOut]
    priority:                int
    is_active:               bool


# ── Transfer type config routes ───────────────────────────────────────────────

@router.get("/{tenant_id}/transfer-types",
            response_model=SuccessResponse[List[TransferTypeConfigOut]])
@require_permission(PERMISSIONS.TRANSFER_TYPE_VIEW)
async def list_transfer_types(
    tenant_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[List[TransferTypeConfigOut]]:
    """Return all transfer type configs with their level permissions."""
    type_rows = (await db.execute(
        text("""
            SELECT id, underlying_type, display_name, description,
                   is_active, sort_order
            FROM   transfer_type_config
            WHERE  tenant_id = :tid
            ORDER  BY sort_order, underlying_type
        """),
        {"tid": str(tenant_id)},
    )).fetchall()

    result: List[TransferTypeConfigOut] = []
    for tr in type_rows:
        perm_rows = (await db.execute(
            text("""
                SELECT ttlp.level_number, ttlp.can_initiate, ttlp.can_receive,
                       thc.level_name
                FROM   transfer_type_level_permissions ttlp
                LEFT JOIN tenant_hierarchy_config thc
                       ON thc.tenant_id    = :tid
                       AND thc.level_number = ttlp.level_number
                WHERE  ttlp.transfer_type_config_id = :ctid
                ORDER  BY ttlp.level_number
            """),
            {"tid": str(tenant_id), "ctid": str(tr.id)},
        )).fetchall()

        result.append(TransferTypeConfigOut(
            id=tr.id,
            underlying_type=tr.underlying_type,
            display_name=tr.display_name,
            description=tr.description,
            is_active=tr.is_active,
            sort_order=tr.sort_order,
            level_permissions=[
                LevelPermissionOut(
                    level_number=p.level_number,
                    level_name=p.level_name,
                    can_initiate=p.can_initiate,
                    can_receive=p.can_receive,
                )
                for p in perm_rows
            ],
        ))
    return SuccessResponse(data=result)


@router.put("/{tenant_id}/transfer-types",
            response_model=SuccessResponse[List[TransferTypeConfigOut]])
@require_permission(PERMISSIONS.TRANSFER_TYPE_MANAGE)
async def upsert_transfer_types(
    tenant_id: uuid.UUID,
    body: List[TransferTypeConfigIn],
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[List[TransferTypeConfigOut]]:
    """Upsert all transfer type configs (insert or update by underlying_type)."""
    for item in body:
        if item.underlying_type not in UNDERLYING_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"underlying_type must be one of {sorted(UNDERLYING_TYPES)}",
            )

    result_ids: List[uuid.UUID] = []
    for item in body:
        existing = (await db.execute(
            text("""
                SELECT id FROM transfer_type_config
                WHERE tenant_id = :tid AND underlying_type = :ut
            """),
            {"tid": str(tenant_id), "ut": item.underlying_type},
        )).fetchone()

        if existing:
            config_id = existing.id
            await db.execute(
                text("""
                    UPDATE transfer_type_config
                    SET display_name = :dn, description = :desc,
                        is_active = :ia, sort_order = :so
                    WHERE id = :id
                """),
                {"dn": item.display_name, "desc": item.description,
                 "ia": item.is_active, "so": item.sort_order,
                 "id": str(config_id)},
            )
        else:
            config_id = uuid.uuid4()
            await db.execute(
                text("""
                    INSERT INTO transfer_type_config
                      (id, tenant_id, underlying_type, display_name, description,
                       is_active, sort_order)
                    VALUES (:id, :tid, :ut, :dn, :desc, :ia, :so)
                """),
                {"id": str(config_id), "tid": str(tenant_id), "ut": item.underlying_type,
                 "dn": item.display_name, "desc": item.description,
                 "ia": item.is_active, "so": item.sort_order},
            )

        # Replace level permissions
        await db.execute(
            text("DELETE FROM transfer_type_level_permissions WHERE transfer_type_config_id = :ctid"),
            {"ctid": str(config_id)},
        )
        for lp in item.level_permissions:
            await db.execute(
                text("""
                    INSERT INTO transfer_type_level_permissions
                      (id, tenant_id, transfer_type_config_id, level_number,
                       can_initiate, can_receive)
                    VALUES (gen_random_uuid(), :tid, :ctid, :ln, :ci, :cr)
                """),
                {"tid": str(tenant_id), "ctid": str(config_id),
                 "ln": lp.level_number, "ci": lp.can_initiate, "cr": lp.can_receive},
            )
        result_ids.append(config_id)

    # Return updated configs — pass as kwargs to avoid @require_permission positional-arg confusion
    return await list_transfer_types(tenant_id=tenant_id, user=user, db=db)


# ── Transfer approval rules routes ────────────────────────────────────────────

@router.get("/{tenant_id}/transfer-approval-rules",
            response_model=SuccessResponse[List[ApprovalRuleOut]])
@require_permission(PERMISSIONS.TRANSFER_APPROVAL_RULE_VIEW)
async def list_approval_rules(
    tenant_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[List[ApprovalRuleOut]]:
    """Return all transfer approval rules for the tenant."""
    rows = (await db.execute(
        text("""
            SELECT
                r.id, r.transfer_type_config_id,
                ttc.display_name             AS transfer_type_name,
                r.source_level, r.destination_level,
                src_lev.level_name           AS source_level_name,
                dst_lev.level_name           AS dest_level_name,
                r.quantity_min, r.quantity_max,
                r.value_min, r.value_max,
                r.threshold_type, r.currency,
                r.approval_steps,
                r.priority, r.is_active
            FROM   transfer_approval_rules r
            JOIN   transfer_type_config ttc
                   ON ttc.id = r.transfer_type_config_id
            LEFT JOIN tenant_hierarchy_config src_lev
                   ON src_lev.tenant_id = :tid AND src_lev.level_number = r.source_level
            LEFT JOIN tenant_hierarchy_config dst_lev
                   ON dst_lev.tenant_id = :tid AND dst_lev.level_number = r.destination_level
            WHERE  r.tenant_id = :tid
            ORDER  BY r.priority, ttc.display_name
        """),
        {"tid": str(tenant_id)},
    )).fetchall()

    result = [
        ApprovalRuleOut(
            id=r.id,
            transfer_type_config_id=r.transfer_type_config_id,
            transfer_type_name=r.transfer_type_name,
            source_level=r.source_level,
            destination_level=r.destination_level,
            source_level_name=r.source_level_name,
            dest_level_name=r.dest_level_name,
            quantity_min=float(r.quantity_min),
            quantity_max=float(r.quantity_max) if r.quantity_max is not None else None,
            value_min=float(r.value_min),
            value_max=float(r.value_max) if r.value_max is not None else None,
            threshold_type=r.threshold_type,
            currency=r.currency,
            approval_steps=[
                ApprovalStepOut(**step) if isinstance(step, dict) else ApprovalStepOut(
                    sequence=i, position_title=None, resolution="ANY",
                    execution_mode="SEQUENTIAL", sla_hours=None,
                )
                for i, step in enumerate(r.approval_steps or [])
            ],
            priority=r.priority,
            is_active=r.is_active,
        )
        for r in rows
    ]
    return SuccessResponse(data=result)


@router.put("/{tenant_id}/transfer-approval-rules",
            response_model=SuccessResponse[List[ApprovalRuleOut]])
@require_permission(PERMISSIONS.TRANSFER_APPROVAL_RULE_MANAGE)
async def upsert_approval_rules(
    tenant_id: uuid.UUID,
    body: List[ApprovalRuleIn],
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[List[ApprovalRuleOut]]:
    """Replace all transfer approval rules for the tenant (full upsert)."""
    for rule in body:
        if rule.threshold_type not in THRESHOLD_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"threshold_type must be one of {sorted(THRESHOLD_TYPES)}",
            )

    # Delete all existing rules and re-insert
    await db.execute(
        text("DELETE FROM transfer_approval_rules WHERE tenant_id = :tid"),
        {"tid": str(tenant_id)},
    )
    for rule in body:
        await db.execute(
            text("""
                INSERT INTO transfer_approval_rules
                  (id, tenant_id, transfer_type_config_id,
                   source_level, destination_level,
                   source_node_id, destination_node_id,
                   quantity_min, quantity_max,
                   value_min, value_max,
                   threshold_type, currency,
                   approval_steps, priority, is_active)
                VALUES
                  (gen_random_uuid(), :tid, :ctid,
                   :sl, :dl, :sn, :dn,
                   :qmin, :qmax, :vmin, :vmax,
                   :tt, :cur, :steps, :prio, :ia)
            """).bindparams(bindparam("steps", type_=types.JSON)),
            {
                "tid":  str(tenant_id),
                "ctid": str(rule.transfer_type_config_id),
                "sl":   rule.source_level, "dl": rule.destination_level,
                "sn":   str(rule.source_node_id) if rule.source_node_id else None,
                "dn":   str(rule.destination_node_id) if rule.destination_node_id else None,
                "qmin": rule.quantity_min, "qmax": rule.quantity_max,
                "vmin": rule.value_min,    "vmax": rule.value_max,
                "tt":   rule.threshold_type, "cur": rule.currency,
                "steps": [s.model_dump() for s in rule.approval_steps],
                "prio": rule.priority, "ia": rule.is_active,
            },
        )

    return await list_approval_rules(tenant_id=tenant_id, user=user, db=db)
