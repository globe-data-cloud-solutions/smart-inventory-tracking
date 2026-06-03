"""Position management endpoints.

Positions describe roles at specific org nodes (e.g. "Warehouse Manager at Addis Main WH").
Personnel are then assigned to positions via personnel_positions.

GET    /tenants/{tenant_id}/positions
POST   /tenants/{tenant_id}/nodes/{node_id}/positions
PATCH  /tenants/{tenant_id}/positions/{position_id}
DELETE /tenants/{tenant_id}/positions/{position_id}
"""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_current_user, get_db_session_for_tenant
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse

router = APIRouter()

# Role codes that may be held via a position.
# SA and TA are not position-based — they're platform/tenant-admin level.
ALLOWED_POSITION_ROLE_CODES = frozenset({"NM", "RM", "LM", "WM", "AU", "RT"})


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class PositionCreate(BaseModel):
    title: str
    role_code: str
    reports_to_position_id: Optional[uuid.UUID] = None


class PositionUpdate(BaseModel):
    title: Optional[str] = None
    reports_to_position_id: Optional[uuid.UUID] = None


class CurrentHolderOut(BaseModel):
    user_id: uuid.UUID
    name: str
    email: str
    assignment_type: str


class PositionOut(BaseModel):
    id: uuid.UUID
    title: str
    role_code: str
    reports_to_position_id: Optional[uuid.UUID]
    reports_to_title: Optional[str]
    current_holder: Optional[CurrentHolderOut]
    is_active: bool


class NodePositionGroupOut(BaseModel):
    node_id: uuid.UUID
    node_name: str
    level_number: int
    positions: List[PositionOut]


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/{tenant_id}/positions",
            response_model=SuccessResponse[List[NodePositionGroupOut]])
@require_permission(PERMISSIONS.POSITION_VIEW)
async def list_positions(
    tenant_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[List[NodePositionGroupOut]]:
    """Return all positions grouped by org node."""
    rows = (await db.execute(
        text("""
            SELECT
                p.id                         AS position_id,
                p.title,
                p.role_code,
                p.reports_to_position_id,
                rp.title                     AS reports_to_title,
                p.is_active,
                n.id                         AS node_id,
                n.name                       AS node_name,
                n.hierarchy_level,
                -- current PRIMARY holder (if any)
                pp.id                        AS pp_id,
                u.id                         AS holder_id,
                u.full_name                  AS holder_name,
                u.email                      AS holder_email,
                pp.assignment_type           AS holder_assignment_type
            FROM   positions p
            JOIN   organization_node n  ON n.id = p.node_id
            LEFT JOIN positions rp      ON rp.id = p.reports_to_position_id
            LEFT JOIN personnel_positions pp
                   ON pp.position_id = p.id
                   AND pp.is_active  = true
                   AND pp.assignment_type = 'PRIMARY'
                   AND (pp.valid_until IS NULL OR pp.valid_until >= CURRENT_DATE)
            LEFT JOIN users u ON u.id = pp.user_id
            WHERE  p.tenant_id = :tid
            AND    p.is_active = true
            ORDER  BY n.hierarchy_level, n.name, p.title
        """),
        {"tid": str(tenant_id)},
    )).fetchall()

    # Group by node
    nodes: dict[str, dict] = {}
    for r in rows:
        nid = str(r.node_id)
        if nid not in nodes:
            nodes[nid] = {
                "node_id":      r.node_id,
                "node_name":    r.node_name,
                "level_number": r.hierarchy_level,
                "positions":    [],
            }
        holder = None
        if r.holder_id:
            holder = CurrentHolderOut(
                user_id=r.holder_id,
                name=r.holder_name,
                email=r.holder_email,
                assignment_type=r.holder_assignment_type,
            )
        nodes[nid]["positions"].append(PositionOut(
            id=r.position_id,
            title=r.title,
            role_code=r.role_code,
            reports_to_position_id=r.reports_to_position_id,
            reports_to_title=r.reports_to_title,
            current_holder=holder,
            is_active=r.is_active,
        ))

    return SuccessResponse(data=[NodePositionGroupOut(**v) for v in nodes.values()])


@router.post("/{tenant_id}/nodes/{node_id}/positions",
             status_code=201,
             response_model=SuccessResponse[PositionOut])
@require_permission(PERMISSIONS.POSITION_MANAGE)
async def create_position(
    tenant_id: uuid.UUID,
    node_id: uuid.UUID,
    body: PositionCreate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[PositionOut]:
    """Create a position at a specific org node.

    SA and TA role codes are not permitted — they are platform/tenant-admin
    roles and do not map to facility positions.
    """
    if body.role_code not in ALLOWED_POSITION_ROLE_CODES:
        raise HTTPException(
            status_code=422,
            detail={
                "code":    "INVALID_ROLE_CODE",
                "message": f"role_code '{body.role_code}' is not permitted for positions. "
                           f"Allowed: {sorted(ALLOWED_POSITION_ROLE_CODES)}",
            },
        )

    # Verify the node belongs to this tenant
    node_row = (await db.execute(
        text("SELECT id FROM organization_node WHERE id = :nid AND tenant_id = :tid"),
        {"nid": str(node_id), "tid": str(tenant_id)},
    )).fetchone()
    if not node_row:
        raise HTTPException(status_code=404, detail="Node not found in this tenant")

    pos_id = uuid.uuid4()
    await db.execute(
        text("""
            INSERT INTO positions
              (id, tenant_id, node_id, title, role_code, reports_to_position_id)
            VALUES (:id, :tid, :nid, :title, :role, :reports_to)
        """),
        {
            "id": str(pos_id), "tid": str(tenant_id), "nid": str(node_id),
            "title": body.title, "role": body.role_code,
            "reports_to": str(body.reports_to_position_id) if body.reports_to_position_id else None,
        },
    )

    # Fetch reports_to title if set
    rp_title: Optional[str] = None
    if body.reports_to_position_id:
        rp_row = (await db.execute(
            text("SELECT title FROM positions WHERE id = :id"),
            {"id": str(body.reports_to_position_id)},
        )).fetchone()
        if rp_row:
            rp_title = rp_row.title

    return SuccessResponse(data=PositionOut(
        id=pos_id,
        title=body.title,
        role_code=body.role_code,
        reports_to_position_id=body.reports_to_position_id,
        reports_to_title=rp_title,
        current_holder=None,
        is_active=True,
    ))


@router.patch("/{tenant_id}/positions/{position_id}",
              response_model=SuccessResponse[PositionOut])
@require_permission(PERMISSIONS.POSITION_MANAGE)
async def update_position(
    tenant_id: uuid.UUID,
    position_id: uuid.UUID,
    body: PositionUpdate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[PositionOut]:
    """Update position title or reporting line. role_code is immutable after creation."""
    row = (await db.execute(
        text("""
            SELECT p.id, p.title, p.role_code, p.reports_to_position_id,
                   p.is_active, rp.title AS rp_title
            FROM   positions p
            LEFT JOIN positions rp ON rp.id = p.reports_to_position_id
            WHERE  p.id = :pid AND p.tenant_id = :tid
        """),
        {"pid": str(position_id), "tid": str(tenant_id)},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Position not found")

    new_title      = body.title                    if body.title      is not None else row.title
    new_reports_to = body.reports_to_position_id   if "reports_to_position_id" in body.model_fields_set \
                     else row.reports_to_position_id

    await db.execute(
        text("""
            UPDATE positions
            SET title = :title, reports_to_position_id = :rpt, updated_at = now()
            WHERE id = :pid AND tenant_id = :tid
        """),
        {"title": new_title, "rpt": str(new_reports_to) if new_reports_to else None,
         "pid": str(position_id), "tid": str(tenant_id)},
    )

    rp_title: Optional[str] = row.rp_title
    if body.reports_to_position_id and body.reports_to_position_id != row.reports_to_position_id:
        rp_row = (await db.execute(
            text("SELECT title FROM positions WHERE id = :id"),
            {"id": str(body.reports_to_position_id)},
        )).fetchone()
        rp_title = rp_row.title if rp_row else None

    return SuccessResponse(data=PositionOut(
        id=row.id,
        title=new_title,
        role_code=row.role_code,
        reports_to_position_id=new_reports_to,
        reports_to_title=rp_title,
        current_holder=None,
        is_active=row.is_active,
    ))


@router.delete("/{tenant_id}/positions/{position_id}",
               response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.POSITION_MANAGE)
async def delete_position(
    tenant_id: uuid.UUID,
    position_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[dict]:
    """Soft-delete a position (is_active=false). Blocked if active personnel assigned."""
    row = (await db.execute(
        text("SELECT id FROM positions WHERE id = :pid AND tenant_id = :tid AND is_active = true"),
        {"pid": str(position_id), "tid": str(tenant_id)},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Position not found or already inactive")

    # Block if active personnel are assigned
    active_count = (await db.execute(
        text("""
            SELECT COUNT(*) FROM personnel_positions
            WHERE position_id = :pid AND is_active = true
              AND (valid_until IS NULL OR valid_until >= CURRENT_DATE)
        """),
        {"pid": str(position_id)},
    )).scalar() or 0
    if active_count > 0:
        raise HTTPException(
            status_code=422,
            detail={
                "code":    "POSITION_HAS_ACTIVE_PERSONNEL",
                "message": f"Position has {active_count} active assignment(s). "
                           "Deactivate or reassign them before deleting this position.",
            },
        )

    await db.execute(
        text("UPDATE positions SET is_active = false, updated_at = now() WHERE id = :pid"),
        {"pid": str(position_id)},
    )
    return SuccessResponse(data={"deleted": True, "position_id": str(position_id)})
