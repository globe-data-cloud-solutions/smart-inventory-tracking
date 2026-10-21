"""Position management endpoints.

Positions describe roles at specific org nodes (e.g. "Warehouse Manager at Addis Main WH").
Personnel are then assigned to positions via personnel_positions.

GET    /tenants/{tenant_id}/positions
POST   /tenants/{tenant_id}/nodes/{node_id}/positions
PATCH  /tenants/{tenant_id}/positions/{position_id}
DELETE /tenants/{tenant_id}/positions/{position_id}
"""

from __future__ import annotations

import json as _json
import uuid
from typing import List, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import bindparam, text, types
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_current_user, get_db_session_for_tenant
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse

router = APIRouter()

# Role codes that may be held via a position.
# SA and TA are not position-based — they're platform/tenant-admin level.
ALLOWED_POSITION_ROLE_CODES = frozenset({"NM", "RM", "LM", "WM", "AU", "RT"})


def _is_duplicate_title_violation(exc: IntegrityError) -> bool:
    """True if this IntegrityError wraps a uq_positions_node_title_active violation."""
    orig = exc.orig
    return (
        isinstance(orig, asyncpg.UniqueViolationError)
        and orig.constraint_name == "uq_positions_node_title_active"
    )


def _duplicate_title_http_exception() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "DUPLICATE_POSITION_TITLE",
            "message": "A position with this title already exists at this node.",
        },
    )


# Matches max org levels (5, see CLAUDE.md §28) plus a safety margin — a real
# reports_to chain can never legitimately be this deep, so hitting this cap
# means existing data already contains an unexpected loop.
_MAX_REPORTS_TO_DEPTH = 20


async def _would_create_cycle(
    db: AsyncSession,
    tenant_id: str,
    position_id: str,
    new_reports_to_id: str,
) -> bool:
    """Walk the reports_to chain starting from new_reports_to_id. If position_id
    is encountered before reaching NULL, assigning new_reports_to_id as
    position_id's reports_to would create a cycle.

    The self-report edge case (position_id == new_reports_to_id) is caught on
    the very first iteration below — current starts at new_reports_to_id, so
    if that equals position_id the loop returns True immediately. No separate
    check is needed.
    """
    visited: set[str] = set()
    current: Optional[str] = new_reports_to_id
    depth = 0
    while current is not None:
        if current == position_id:
            return True  # cycle detected
        if current in visited:
            return True  # unexpected loop already present in existing data
        visited.add(current)
        depth += 1
        if depth > _MAX_REPORTS_TO_DEPTH:
            return True  # defensive cap — see _MAX_REPORTS_TO_DEPTH
        row = (
            await db.execute(
                text(
                    "SELECT reports_to_position_id FROM positions WHERE id = :id AND tenant_id = :tid"
                ),
                {"id": current, "tid": tenant_id},
            )
        ).fetchone()
        if row is None:
            break
        current = str(row.reports_to_position_id) if row.reports_to_position_id else None
    return False


def _circular_reports_to_http_exception() -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={
            "code": "CIRCULAR_REPORTS_TO",
            "message": "This reports-to assignment would create a circular chain. "
            "A position cannot report to itself or to any of its own descendants.",
        },
    )


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class PositionCreate(BaseModel):
    title: str
    role_code: str
    reports_to_position_id: Optional[uuid.UUID] = None


class PositionUpdate(BaseModel):
    title: Optional[str] = None
    role_code: Optional[str] = None
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


class TenantPositionFlatOut(BaseModel):
    id: uuid.UUID
    title: str
    role_code: str
    level_number: int
    level_name: str
    node_id: uuid.UUID
    node_name: str
    display_label: str
    reports_to_position_id: Optional[uuid.UUID]
    reports_to_title: Optional[str]


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get(
    "/{tenant_id}/positions/flat", response_model=SuccessResponse[List[TenantPositionFlatOut]]
)
@require_permission(PERMISSIONS.POSITION_VIEW)
async def list_positions_flat(
    tenant_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[List[TenantPositionFlatOut]]:
    """Return a flat list of all active positions across all nodes.

    Used by frontend dropdowns that need a single tenant-wide list of
    positions with enough context (node + level) to disambiguate
    same-titled positions at different facilities.
    """
    rows = (
        await db.execute(
            text("""
            SELECT
                p.id                    AS position_id,
                p.title,
                p.role_code,
                p.reports_to_position_id,
                p2.title                AS reports_to_title,
                n.id                    AS node_id,
                n.name                  AS node_name,
                thc.level_number        AS level_number,
                thc.level_name          AS level_name
            FROM   positions p
            JOIN   organization_node n
                   ON n.id = p.node_id
            JOIN   tenant_hierarchy_config thc
                   ON thc.tenant_id = p.tenant_id
                  AND thc.level_number = n.hierarchy_level
            LEFT JOIN positions p2
                   ON p2.id = p.reports_to_position_id
            WHERE  p.tenant_id = :tid
              AND  p.is_active = true
            ORDER  BY thc.level_number, n.name, p.title
        """),
            {"tid": str(tenant_id)},
        )
    ).fetchall()

    return SuccessResponse(
        data=[
            TenantPositionFlatOut(
                id=r.position_id,
                title=r.title,
                role_code=r.role_code,
                level_number=r.level_number,
                level_name=r.level_name,
                node_id=r.node_id,
                node_name=r.node_name,
                display_label=f"{r.title} ({r.role_code}) — {r.node_name} (L{r.level_number})",
                reports_to_position_id=r.reports_to_position_id,
                reports_to_title=r.reports_to_title,
            )
            for r in rows
        ]
    )


@router.get("/{tenant_id}/positions", response_model=SuccessResponse[List[NodePositionGroupOut]])
@require_permission(PERMISSIONS.POSITION_VIEW)
async def list_positions(
    tenant_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[List[NodePositionGroupOut]]:
    """Return all positions grouped by org node."""
    rows = (
        await db.execute(
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
        )
    ).fetchall()

    # Group by node
    nodes: dict[str, dict] = {}
    for r in rows:
        nid = str(r.node_id)
        if nid not in nodes:
            nodes[nid] = {
                "node_id": r.node_id,
                "node_name": r.node_name,
                "level_number": r.hierarchy_level,
                "positions": [],
            }
        holder = None
        if r.holder_id:
            holder = CurrentHolderOut(
                user_id=r.holder_id,
                name=r.holder_name,
                email=r.holder_email,
                assignment_type=r.holder_assignment_type,
            )
        nodes[nid]["positions"].append(
            PositionOut(
                id=r.position_id,
                title=r.title,
                role_code=r.role_code,
                reports_to_position_id=r.reports_to_position_id,
                reports_to_title=r.reports_to_title,
                current_holder=holder,
                is_active=r.is_active,
            )
        )

    return SuccessResponse(data=[NodePositionGroupOut(**v) for v in nodes.values()])


@router.post(
    "/{tenant_id}/nodes/{node_id}/positions",
    status_code=201,
    response_model=SuccessResponse[PositionOut],
)
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
                "code": "INVALID_ROLE_CODE",
                "message": f"role_code '{body.role_code}' is not permitted for positions. "
                f"Allowed: {sorted(ALLOWED_POSITION_ROLE_CODES)}",
            },
        )

    # Verify the node belongs to this tenant
    node_row = (
        await db.execute(
            text("SELECT id FROM organization_node WHERE id = :nid AND tenant_id = :tid"),
            {"nid": str(node_id), "tid": str(tenant_id)},
        )
    ).fetchone()
    if not node_row:
        raise HTTPException(status_code=404, detail="Node not found in this tenant")

    pos_id = uuid.uuid4()
    try:
        await db.execute(
            text("""
                INSERT INTO positions
                  (id, tenant_id, node_id, title, role_code, reports_to_position_id)
                VALUES (:id, :tid, :nid, :title, :role, :reports_to)
            """),
            {
                "id": str(pos_id),
                "tid": str(tenant_id),
                "nid": str(node_id),
                "title": body.title,
                "role": body.role_code,
                "reports_to": str(body.reports_to_position_id)
                if body.reports_to_position_id
                else None,
            },
        )
    except IntegrityError as exc:
        if _is_duplicate_title_violation(exc):
            raise _duplicate_title_http_exception() from exc
        raise

    # Fetch reports_to title if set
    rp_title: Optional[str] = None
    if body.reports_to_position_id:
        rp_row = (
            await db.execute(
                text("SELECT title FROM positions WHERE id = :id AND tenant_id = :tid"),
                {"id": str(body.reports_to_position_id), "tid": str(tenant_id)},
            )
        ).fetchone()
        if rp_row:
            rp_title = rp_row.title

    return SuccessResponse(
        data=PositionOut(
            id=pos_id,
            title=body.title,
            role_code=body.role_code,
            reports_to_position_id=body.reports_to_position_id,
            reports_to_title=rp_title,
            current_holder=None,
            is_active=True,
        )
    )


@router.patch("/{tenant_id}/positions/{position_id}", response_model=SuccessResponse[PositionOut])
@require_permission(PERMISSIONS.POSITION_MANAGE)
async def update_position(
    tenant_id: uuid.UUID,
    position_id: uuid.UUID,
    body: PositionUpdate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[PositionOut]:
    """Update position title, role, or reporting line."""
    row = (
        await db.execute(
            text("""
            SELECT p.id, p.title, p.role_code, p.reports_to_position_id,
                   p.is_active, rp.title AS rp_title
            FROM   positions p
            LEFT JOIN positions rp ON rp.id = p.reports_to_position_id
            WHERE  p.id = :pid AND p.tenant_id = :tid
        """),
            {"pid": str(position_id), "tid": str(tenant_id)},
        )
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Position not found")

    if body.role_code is not None and body.role_code not in ALLOWED_POSITION_ROLE_CODES:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_ROLE_CODE",
                "message": f"role_code '{body.role_code}' is not permitted for positions. "
                f"Allowed: {sorted(ALLOWED_POSITION_ROLE_CODES)}",
            },
        )

    new_title = body.title if body.title is not None else row.title
    new_role_code = body.role_code if body.role_code is not None else row.role_code
    new_reports_to = (
        body.reports_to_position_id
        if "reports_to_position_id" in body.model_fields_set
        else row.reports_to_position_id
    )

    if new_reports_to is not None and await _would_create_cycle(
        db, str(tenant_id), str(position_id), str(new_reports_to)
    ):
        raise _circular_reports_to_http_exception()

    try:
        await db.execute(
            text("""
                UPDATE positions
                SET title = :title, role_code = :role, reports_to_position_id = :rpt, updated_at = now()
                WHERE id = :pid AND tenant_id = :tid
            """),
            {
                "title": new_title,
                "role": new_role_code,
                "rpt": str(new_reports_to) if new_reports_to else None,
                "pid": str(position_id),
                "tid": str(tenant_id),
            },
        )
    except IntegrityError as exc:
        if _is_duplicate_title_violation(exc):
            raise _duplicate_title_http_exception() from exc
        raise

    # Cascade title change into approval_steps JSONB so display names stay in sync
    if body.title is not None and body.title != row.title:
        rule_rows = (
            await db.execute(
                text(
                    "SELECT id, approval_steps FROM transfer_approval_rules WHERE tenant_id = :tid"
                ),
                {"tid": str(tenant_id)},
            )
        ).fetchall()
        for rule_row in rule_rows:
            steps = rule_row.approval_steps
            if isinstance(steps, str):
                steps = _json.loads(steps)
            if not isinstance(steps, list):
                continue
            changed = False
            for s in steps:
                if isinstance(s, dict) and s.get("position_id") == str(position_id):
                    s["position_title"] = new_title
                    changed = True
            if changed:
                await db.execute(
                    text(
                        "UPDATE transfer_approval_rules SET approval_steps = :steps WHERE id = :rid"
                    ).bindparams(bindparam("steps", type_=types.JSON)),
                    {"steps": steps, "rid": str(rule_row.id)},
                )

    rp_title: Optional[str] = row.rp_title
    if body.reports_to_position_id and body.reports_to_position_id != row.reports_to_position_id:
        rp_row = (
            await db.execute(
                text("SELECT title FROM positions WHERE id = :id AND tenant_id = :tid"),
                {"id": str(body.reports_to_position_id), "tid": str(tenant_id)},
            )
        ).fetchone()
        rp_title = rp_row.title if rp_row else None

    return SuccessResponse(
        data=PositionOut(
            id=row.id,
            title=new_title,
            role_code=new_role_code,
            reports_to_position_id=new_reports_to,
            reports_to_title=rp_title,
            current_holder=None,
            is_active=row.is_active,
        )
    )


@router.delete("/{tenant_id}/positions/{position_id}", response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.POSITION_MANAGE)
async def delete_position(
    tenant_id: uuid.UUID,
    position_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[dict]:
    """Soft-delete a position (is_active=false). Blocked if active personnel assigned."""
    row = (
        await db.execute(
            text(
                "SELECT id FROM positions WHERE id = :pid AND tenant_id = :tid AND is_active = true"
            ),
            {"pid": str(position_id), "tid": str(tenant_id)},
        )
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Position not found or already inactive")

    # Block if active personnel are assigned
    active_count = (
        await db.execute(
            text("""
            SELECT COUNT(*) FROM personnel_positions
            WHERE position_id = :pid AND is_active = true
              AND (valid_until IS NULL OR valid_until >= CURRENT_DATE)
        """),
            {"pid": str(position_id)},
        )
    ).scalar() or 0
    if active_count > 0:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "POSITION_HAS_ACTIVE_PERSONNEL",
                "message": f"Position has {active_count} active assignment(s). "
                "Deactivate or reassign them before deleting this position.",
            },
        )

    await db.execute(
        text("UPDATE positions SET is_active = false, updated_at = now() WHERE id = :pid"),
        {"pid": str(position_id)},
    )
    return SuccessResponse(data={"deleted": True, "position_id": str(position_id)})
