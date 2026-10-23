"""Org hierarchy and org node management endpoints.

Hierarchy config:   GET/PUT /tenants/{tenant_id}/hierarchy/config
Org node CRUD:      GET/POST /tenants/{tenant_id}/nodes
                    PATCH/DELETE /tenants/{tenant_id}/nodes/{node_id}
Supply routes:      POST /tenants/{tenant_id}/nodes/{node_id}/supply-routes
"""

from __future__ import annotations

import uuid
from typing import List, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_current_user, get_db_session_for_tenant
from shared.permissions.audit import audit_log
from shared.permissions.middleware import require_permission
from shared.permissions.plan_middleware import check_plan_create_warehouse
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse

router = APIRouter()


def _is_duplicate_level_name_violation(exc: IntegrityError) -> bool:
    """True if this IntegrityError wraps a uq_hierarchy_config_tenant_name violation."""
    orig = exc.orig
    return (
        isinstance(orig, asyncpg.UniqueViolationError)
        and orig.constraint_name == "uq_hierarchy_config_tenant_name"
    )


def _duplicate_level_name_http_exception() -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={
            "code": "DUPLICATE_LEVEL_NAME",
            "message": "A level with this name already exists for this tenant.",
        },
    )


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class HierarchyLevelIn(BaseModel):
    level_number: int
    level_name: str
    default_role_code: Optional[str] = None
    role_display_label: Optional[str] = None
    is_stock_holding: bool = True


class HierarchyLevelOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    level_number: int
    level_name: str
    default_role_code: Optional[str]
    role_display_label: Optional[str]
    is_stock_holding: bool
    is_active: bool
    # Active organisation nodes at this level. A saved level's role is locked
    # while this is above zero (see set_hierarchy_level_role).
    active_node_count: int = 0


class HierarchyLevelRoleIn(BaseModel):
    default_role_code: str


# Roles a level can carry. Never SA or TA (CLAUDE.md §28). Required on every
# level: nodes are created from the level's role.
LEVEL_ROLE_CODES = ("NM", "RM", "LM", "WM", "AU")

_ACTIVE_NODE_COUNT_SQL = (
    "(SELECT count(*) FROM organization_node n "
    "WHERE n.tenant_id = tenant_hierarchy_config.tenant_id "
    "AND n.hierarchy_level = tenant_hierarchy_config.level_number "
    "AND n.is_active = true)"
)


async def _active_node_count(db: AsyncSession, tenant_id: uuid.UUID, level_number: int) -> int:
    row = await db.execute(
        text(
            "SELECT count(*) AS n FROM organization_node "
            "WHERE tenant_id = :tid AND hierarchy_level = :lvl AND is_active = true"
        ),
        {"tid": str(tenant_id), "lvl": level_number},
    )
    return int(row.fetchone().n)


def _role_locked_http_exception(level_number: int, node_count: int) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "LEVEL_ROLE_LOCKED",
            "level_number": level_number,
            "node_count": node_count,
            "message": (
                "This level's role cannot change while locations exist at it. "
                "Remove or move those locations first."
            ),
        },
    )


class HierarchyLevelRename(BaseModel):
    level_name: Optional[str] = None
    role_display_label: Optional[str] = None
    is_stock_holding: Optional[bool] = None

    @field_validator("level_name")
    @classmethod
    def _validate_level_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not (2 <= len(v) <= 50):
            raise ValueError("level_name must be between 2 and 50 characters")
        return v

    @field_validator("role_display_label")
    @classmethod
    def _validate_role_display_label(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if v == "":
            return None  # clearing reverts to the system default role name
        if not (2 <= len(v) <= 50):
            raise ValueError("role_display_label must be between 2 and 50 characters")
        return v


class OrgNodeCreate(BaseModel):
    name: str
    level_number: int
    parent_node_id: Optional[uuid.UUID] = None
    is_stock_holding: bool = True
    address: Optional[str] = None


class OrgNodeUpdate(BaseModel):
    name: Optional[str] = None
    is_stock_holding: Optional[bool] = None
    address: Optional[str] = None


class OrgNodeOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    code: str
    address: Optional[str] = None
    hierarchy_level: int
    level_name: Optional[str]
    is_stock_holding: bool
    parent_node_id: Optional[uuid.UUID]
    manager_name: Optional[str]
    manager_role: Optional[str]
    is_active: bool
    children: List["OrgNodeOut"] = []

    model_config = {"from_attributes": True}


OrgNodeOut.model_rebuild()


class SupplyRouteIn(BaseModel):
    primary_source_id: uuid.UUID
    secondary_source_id: Optional[uuid.UUID] = None


class SupplyRouteOut(BaseModel):
    node_id: uuid.UUID
    primary_source_id: Optional[uuid.UUID]
    secondary_source_id: Optional[uuid.UUID]


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _get_level_name(db: AsyncSession, tenant_id: str, level_number: int) -> Optional[str]:
    row = await db.execute(
        text(
            "SELECT level_name FROM tenant_hierarchy_config "
            "WHERE tenant_id = :tid AND level_number = :lvl"
        ),
        {"tid": tenant_id, "lvl": level_number},
    )
    r = row.fetchone()
    return r[0] if r else None


async def _node_manager(
    db: AsyncSession, node_id: str, tenant_id: str
) -> tuple[Optional[str], Optional[str]]:
    """Manager of a node = the PRIMARY holder of its highest-authority position.

    Same rule as the tree query in list_org_nodes, for one node. Nothing is
    read from the request body (review bug 10).
    """
    row = await db.execute(
        text(
            "SELECT u.full_name AS manager_name, p.role_code AS manager_role "
            "FROM positions p "
            "JOIN personnel_positions pp "
            "  ON pp.position_id = p.id "
            " AND pp.assignment_type = 'PRIMARY' "
            " AND pp.is_active = true "
            " AND (pp.valid_until IS NULL OR pp.valid_until >= CURRENT_DATE) "
            "JOIN users u ON u.id = pp.user_id AND u.is_active = true "
            "WHERE p.node_id = :nid AND p.tenant_id = :tid AND p.is_active = true "
            "ORDER BY CASE p.role_code "
            "  WHEN 'NM' THEN 8 WHEN 'RM' THEN 7 WHEN 'LM' THEN 6 "
            "  WHEN 'WM' THEN 6 WHEN 'SA_GT' THEN 4 ELSE 0 END DESC "
            "LIMIT 1"
        ),
        {"nid": node_id, "tid": tenant_id},
    )
    r = row.fetchone()
    return (r.manager_name, r.manager_role) if r else (None, None)


async def _build_tree(
    db: AsyncSession,
    tenant_id: str,
    nodes_by_parent: dict[Optional[str], list[dict]],
    level_names: dict[int, str],
    parent_id: Optional[str] = None,
) -> list[OrgNodeOut]:
    result = []
    for node in nodes_by_parent.get(parent_id, []):
        node_id_str = str(node["id"])
        children = await _build_tree(db, tenant_id, nodes_by_parent, level_names, node_id_str)
        manager_name = node.get("manager_name")
        manager_role = node.get("manager_role")
        result.append(
            OrgNodeOut(
                id=node["id"],
                tenant_id=node["tenant_id"],
                name=node["name"],
                code=node["code"],
                address=node.get("address"),
                hierarchy_level=node["hierarchy_level"],
                level_name=level_names.get(node["hierarchy_level"]),
                is_stock_holding=node["is_stock_holding"],
                parent_node_id=node.get("parent_node_id"),
                manager_name=manager_name,
                manager_role=manager_role,
                is_active=node["is_active"],
                children=children,
            )
        )
    return result


def _derive_code(tenant_id: str, name: str, level: int) -> str:
    """Derive a short code from the node name (max 10 chars, uppercase, alphanumeric)."""
    prefix = "".join(c for c in name.upper() if c.isalnum())[:8]
    return f"{prefix}{level}"


async def _node_stock_activity_blocker(
    db: AsyncSession,
    tenant_id: str,
    node_id: str,
    checks: tuple[str, ...] = ("transfers", "adjustments", "stock"),
) -> Optional[dict]:
    """Runs the requested subset of open-transfers / pending-adjustments / stock-on-hand
    checks, in that order, and returns the first 422 detail dict hit, or None if every
    requested check passes. `checks` lets deactivate_org_node split this around its
    sole-user check (which has no equivalent here) to keep its existing check order,
    while update_org_node's stock-holding true→false guard runs all three in one call."""
    if "transfers" in checks:
        transfer_row = await db.execute(
            text(
                "SELECT COUNT(*) AS cnt FROM transfer_orders "
                "WHERE (from_warehouse_id = :wid OR to_warehouse_id = :wid) "
                "AND status NOT IN ('COMPLETED', 'CANCELLED', 'REJECTED') "
                "AND tenant_id = :tid"
            ),
            {"wid": node_id, "tid": tenant_id},
        )
        transfer_count = transfer_row.fetchone()
        if transfer_count and transfer_count.cnt > 0:
            return {
                "code": "NODE_HAS_OPEN_TRANSFERS",
                "message": f"Cannot deactivate — this location has {transfer_count.cnt} "
                "open transfer(s). Complete or cancel them first.",
            }

    if "adjustments" in checks:
        adj_row = await db.execute(
            text(
                "SELECT COUNT(*) AS cnt FROM adjustment_orders "
                "WHERE warehouse_id = :wid "
                "AND status NOT IN ('POSTED', 'CANCELLED', 'REJECTED') "
                "AND tenant_id = :tid"
            ),
            {"wid": node_id, "tid": tenant_id},
        )
        adj_count = adj_row.fetchone()
        if adj_count and adj_count.cnt > 0:
            return {
                "code": "NODE_HAS_PENDING_ADJUSTMENTS",
                "message": f"Cannot deactivate — this location has {adj_count.cnt} "
                "pending adjustment(s).",
            }

    if "stock" in checks:
        stock_row = await db.execute(
            text(
                "SELECT COALESCE(SUM(quantity), 0) AS total "
                "FROM inventory_balances "
                "WHERE warehouse_id = :wid AND tenant_id = :tid"
            ),
            {"wid": node_id, "tid": tenant_id},
        )
        stock_total = stock_row.fetchone()
        if stock_total and float(stock_total.total) > 0:
            return {
                "code": "NODE_HAS_STOCK",
                "message": "Cannot deactivate — this location has stock on hand. "
                "Transfer or adjust stock to zero first.",
            }

    return None


# ── Hierarchy config endpoints ─────────────────────────────────────────────────


@router.get(
    "/{tenant_id}/hierarchy/config",
    response_model=SuccessResponse[List[HierarchyLevelOut]],
)
@require_permission(PERMISSIONS.TENANT_VIEW)
async def get_hierarchy_config(
    tenant_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[List[HierarchyLevelOut]]:
    rows = await db.execute(
        text(
            "SELECT id, tenant_id, level_number, level_name, default_role_code, "
            "role_display_label, is_stock_holding, is_active, "
            f"{_ACTIVE_NODE_COUNT_SQL} AS active_node_count "
            "FROM tenant_hierarchy_config "
            "WHERE tenant_id = :tid AND is_active = true ORDER BY level_number"
        ),
        {"tid": str(tenant_id)},
    )
    levels = [
        HierarchyLevelOut(
            id=r.id,
            tenant_id=r.tenant_id,
            level_number=r.level_number,
            level_name=r.level_name,
            default_role_code=r.default_role_code,
            role_display_label=r.role_display_label,
            is_stock_holding=r.is_stock_holding,
            is_active=r.is_active,
            active_node_count=r.active_node_count,
        )
        for r in rows.fetchall()
    ]
    return SuccessResponse(data=levels)


@router.put(
    "/{tenant_id}/hierarchy/config",
    response_model=SuccessResponse[List[HierarchyLevelOut]],
)
@require_permission(PERMISSIONS.TENANT_MANAGE)
async def upsert_hierarchy_config(
    tenant_id: uuid.UUID,
    body: List[HierarchyLevelIn],
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[List[HierarchyLevelOut]]:
    if not body:
        raise HTTPException(status_code=400, detail="At least one level is required")

    # G2 — reject duplicate level_number values within the same payload before
    # they reach the DB, where ON CONFLICT would otherwise upsert each one in
    # turn and silently let the last write win.
    level_numbers = [level.level_number for level in body]
    if len(level_numbers) != len(set(level_numbers)):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "DUPLICATE_LEVEL_NUMBER",
                "message": "Each level must have a unique level number.",
            },
        )

    for level in body:
        if not (1 <= level.level_number <= 5):
            raise HTTPException(
                status_code=422,
                detail=f"level_number must be between 1 and 5, got {level.level_number}",
            )

    # Contiguity guard — submitted level_numbers must be exactly 1..len(body),
    # no gaps or duplicates, before any write happens.
    if sorted(level_numbers) != list(range(1, len(body) + 1)):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "LEVELS_NOT_CONTIGUOUS",
                "message": "Level numbers must be contiguous, starting at 1 with no gaps.",
            },
        )

    existing_count = (
        await db.execute(
            text(
                "SELECT COUNT(*) FROM tenant_hierarchy_config "
                "WHERE tenant_id = :tid AND is_active = true"
            ),
            {"tid": str(tenant_id)},
        )
    ).scalar() or 0
    # G3a — directional level lock: growing is always safe (new levels
    # are appended below existing nodes and have no data yet).
    # Shrinking is only blocked if nodes exist at the levels being removed.
    if existing_count > 0 and len(body) < existing_count:
        # Find the highest level_number currently used by any active node
        max_used_level = (
            await db.execute(
                text(
                    "SELECT COALESCE(MAX(hierarchy_level), 0) "
                    "FROM organization_node "
                    "WHERE tenant_id = :tid AND is_active = true"
                ),
                {"tid": str(tenant_id)},
            )
        ).scalar() or 0
        if len(body) < max_used_level:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "LEVEL_COUNT_LOCKED",
                    "message": (
                        f"Cannot remove level {max_used_level} — active org nodes "
                        f"exist at that level. Remove or move those nodes first."
                    ),
                },
            )
    # Growing (len(body) > existing_count) always passes — no check needed.

    # G4 — for every EXISTING active level whose is_stock_holding would flip
    # true → false in this replace, block if any active stock-holding node
    # still sits at that level. Mirrors the PATCH guard below so the full-replace
    # path can't bypass it. New levels in this payload are unaffected.
    if existing_count > 0:
        existing_levels_rows = (
            await db.execute(
                text(
                    "SELECT level_number, is_stock_holding FROM tenant_hierarchy_config "
                    "WHERE tenant_id = :tid AND is_active = true"
                ),
                {"tid": str(tenant_id)},
            )
        ).fetchall()
        existing_stock_by_level = {r.level_number: r.is_stock_holding for r in existing_levels_rows}

        for level in body:
            was_stock_holding = existing_stock_by_level.get(level.level_number)
            if was_stock_holding is True and level.is_stock_holding is False:
                blocked_nodes = (
                    await db.execute(
                        text(
                            "SELECT id, name FROM organization_node "
                            "WHERE tenant_id = :tid AND hierarchy_level = :lvl "
                            "AND is_active = true AND is_stock_holding = true"
                        ),
                        {"tid": str(tenant_id), "lvl": level.level_number},
                    )
                ).fetchall()
                if blocked_nodes:
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "code": "LEVEL_HAS_STOCK_NODES",
                            "nodes": [{"id": str(n.id), "name": n.name} for n in blocked_nodes],
                            "message": "Switch these locations to approval-only first.",
                        },
                    )

    # Roles are required on every level, and a saved level's role is locked
    # while active nodes exist at that level.
    for level in body:
        if level.default_role_code not in LEVEL_ROLE_CODES:
            raise HTTPException(
                status_code=422,
                detail={"code": "LEVEL_ROLE_REQUIRED", "level_number": level.level_number},
            )
    saved_role_rows = (
        await db.execute(
            text(
                "SELECT level_number, default_role_code FROM tenant_hierarchy_config "
                "WHERE tenant_id = :tid AND is_active = true"
            ),
            {"tid": str(tenant_id)},
        )
    ).fetchall()
    saved_role_by_level = {r.level_number: r.default_role_code for r in saved_role_rows}
    role_overrides: list[tuple[int, str | None, str, int]] = []
    for level in body:
        previous_role = saved_role_by_level.get(level.level_number)
        if previous_role and previous_role != level.default_role_code:
            node_count = await _active_node_count(db, tenant_id, level.level_number)
            if node_count:
                if getattr(user, "role", "") != "SA":
                    raise _role_locked_http_exception(level.level_number, node_count)
                role_overrides.append(
                    (level.level_number, previous_role, level.default_role_code, node_count)
                )

    try:
        for level in body:
            await db.execute(
                text(
                    """
                    INSERT INTO tenant_hierarchy_config
                        (tenant_id, level_number, level_name, default_role_code,
                         role_display_label, is_stock_holding, is_active)
                    VALUES (:tid, :lvl, :name, :role, :label, :stock, true)
                    ON CONFLICT (tenant_id, level_number) DO UPDATE SET
                        level_name        = EXCLUDED.level_name,
                        default_role_code = EXCLUDED.default_role_code,
                        role_display_label= EXCLUDED.role_display_label,
                        is_stock_holding  = EXCLUDED.is_stock_holding,
                        is_active         = true,
                        updated_at        = now()
                    """
                ),
                {
                    "tid": str(tenant_id),
                    "lvl": level.level_number,
                    "name": level.level_name,
                    "role": level.default_role_code,
                    "label": level.role_display_label,
                    "stock": level.is_stock_holding,
                },
            )
    except IntegrityError as exc:
        if _is_duplicate_level_name_violation(exc):
            raise _duplicate_level_name_http_exception() from exc
        raise

    for level_number, from_role, to_role, node_count in role_overrides:
        await audit_log(
            user,
            "hierarchy:level_role_changed",
            {
                "resource_type": "hierarchy_level",
                "level_number": level_number,
                "from_role": from_role,
                "to_role": to_role,
                "override": True,
                "active_node_count": node_count,
            },
            "SUCCESS",
            f"SA override of locked role ({node_count} nodes): {from_role} -> {to_role}",
            db=db,
        )

    # Deactivate any levels in the DB that are NOT in the submitted body.
    # This makes PUT a full replace, not an additive upsert.
    submitted_level_numbers = [level.level_number for level in body]
    if submitted_level_numbers:
        placeholders = ", ".join(f":lv{i}" for i in range(len(submitted_level_numbers)))
        params: dict = {"tid": str(tenant_id)}
        for i, lv in enumerate(submitted_level_numbers):
            params[f"lv{i}"] = lv
        await db.execute(
            text(
                f"UPDATE tenant_hierarchy_config "
                f"SET is_active = false, updated_at = now() "
                f"WHERE tenant_id = :tid AND level_number NOT IN ({placeholders})"
            ),
            params,
        )

    rows = await db.execute(
        text(
            "SELECT id, tenant_id, level_number, level_name, default_role_code, "
            "role_display_label, is_stock_holding, is_active, "
            f"{_ACTIVE_NODE_COUNT_SQL} AS active_node_count "
            "FROM tenant_hierarchy_config "
            "WHERE tenant_id = :tid AND is_active = true ORDER BY level_number"
        ),
        {"tid": str(tenant_id)},
    )
    levels = [
        HierarchyLevelOut(
            id=r.id,
            tenant_id=r.tenant_id,
            level_number=r.level_number,
            level_name=r.level_name,
            default_role_code=r.default_role_code,
            role_display_label=r.role_display_label,
            is_stock_holding=r.is_stock_holding,
            is_active=r.is_active,
            active_node_count=r.active_node_count,
        )
        for r in rows.fetchall()
    ]
    return SuccessResponse(data=levels)


@router.patch(
    "/{tenant_id}/hierarchy/config/{level_id}/role",
    response_model=SuccessResponse[HierarchyLevelOut],
)
@require_permission(PERMISSIONS.TENANT_MANAGE)
async def set_hierarchy_level_role(
    tenant_id: uuid.UUID,
    level_id: uuid.UUID,
    body: HierarchyLevelRoleIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[HierarchyLevelOut]:
    """Set or change a level's role (TA and SA).

    Allowed while no active node exists at the level. A level that has no role
    yet (saved before roles were required) can always be given one. Once nodes
    exist, the role is locked (409 LEVEL_ROLE_LOCKED); removing or moving those
    nodes unlocks it again.
    """
    if body.default_role_code not in LEVEL_ROLE_CODES:
        raise HTTPException(status_code=422, detail={"code": "LEVEL_ROLE_INVALID"})

    current = (
        await db.execute(
            text(
                "SELECT id, level_number, default_role_code FROM tenant_hierarchy_config "
                "WHERE id = :id AND tenant_id = :tid AND is_active = true"
            ),
            {"id": str(level_id), "tid": str(tenant_id)},
        )
    ).fetchone()
    if not current:
        raise HTTPException(status_code=404, detail="Hierarchy level not found")

    node_count = await _active_node_count(db, tenant_id, current.level_number)
    if current.default_role_code != body.default_role_code:
        overridden = bool(current.default_role_code and node_count)
        if overridden and getattr(user, "role", "") != "SA":
            raise _role_locked_http_exception(current.level_number, node_count)

        await db.execute(
            text(
                "UPDATE tenant_hierarchy_config SET default_role_code = :role, updated_at = now() "
                "WHERE id = :id AND tenant_id = :tid"
            ),
            {"role": body.default_role_code, "id": str(level_id), "tid": str(tenant_id)},
        )
        await audit_log(
            user,
            "hierarchy:level_role_changed",
            {
                "resource_type": "hierarchy_level",
                "resource_id": str(level_id),
                "level_number": current.level_number,
                "from_role": current.default_role_code,
                "to_role": body.default_role_code,
                "override": overridden,
                "active_node_count": node_count,
            },
            "SUCCESS",
            (
                f"SA override of locked role ({node_count} nodes): "
                f"{current.default_role_code} -> {body.default_role_code}"
                if overridden
                else f"role {current.default_role_code or 'unset'} -> {body.default_role_code}"
            ),
            db=db,
        )

    row = (
        await db.execute(
            text(
                "SELECT id, tenant_id, level_number, level_name, default_role_code, "
                "role_display_label, is_stock_holding, is_active "
                "FROM tenant_hierarchy_config WHERE id = :id AND tenant_id = :tid"
            ),
            {"id": str(level_id), "tid": str(tenant_id)},
        )
    ).fetchone()
    return SuccessResponse(
        data=HierarchyLevelOut(
            id=row.id,
            tenant_id=row.tenant_id,
            level_number=row.level_number,
            level_name=row.level_name,
            default_role_code=row.default_role_code,
            role_display_label=row.role_display_label,
            is_stock_holding=row.is_stock_holding,
            is_active=row.is_active,
            active_node_count=node_count,
        )
    )


@router.patch(
    "/{tenant_id}/hierarchy/config/{level_id}",
    response_model=SuccessResponse[HierarchyLevelOut],
)
@require_permission(PERMISSIONS.TENANT_MANAGE)
async def rename_hierarchy_level(
    tenant_id: uuid.UUID,
    level_id: uuid.UUID,
    body: HierarchyLevelRename,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[HierarchyLevelOut]:
    """Rename a level, set its role_display_label, and/or toggle is_stock_holding.
    level_number is immutable. The role is changed through set_hierarchy_level_role."""
    fields_set = body.model_fields_set
    set_clauses: list[str] = []
    params: dict[str, object] = {"id": str(level_id), "tid": str(tenant_id)}

    if "level_name" in fields_set:
        if body.level_name is None:
            raise HTTPException(status_code=422, detail="level_name cannot be cleared")
        set_clauses.append("level_name = :name")
        params["name"] = body.level_name

    if "role_display_label" in fields_set:
        set_clauses.append("role_display_label = :label")
        params["label"] = body.role_display_label  # None clears it back to the system default

    if "is_stock_holding" in fields_set:
        # true → false is only allowed if no active node at this level still
        # holds stock. false → true is always allowed — nodes are unaffected.
        if body.is_stock_holding is False:
            current_row = (
                await db.execute(
                    text(
                        "SELECT level_number, is_stock_holding FROM tenant_hierarchy_config "
                        "WHERE id = :id AND tenant_id = :tid"
                    ),
                    {"id": str(level_id), "tid": str(tenant_id)},
                )
            ).fetchone()
            if current_row is not None and current_row.is_stock_holding:
                blocked_nodes = (
                    await db.execute(
                        text(
                            "SELECT id, name FROM organization_node "
                            "WHERE tenant_id = :tid AND hierarchy_level = :lvl "
                            "AND is_active = true AND is_stock_holding = true"
                        ),
                        {"tid": str(tenant_id), "lvl": current_row.level_number},
                    )
                ).fetchall()
                if blocked_nodes:
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "code": "LEVEL_HAS_STOCK_NODES",
                            "nodes": [{"id": str(n.id), "name": n.name} for n in blocked_nodes],
                            "message": "Switch these locations to approval-only first.",
                        },
                    )
        set_clauses.append("is_stock_holding = :stock_holding")
        params["stock_holding"] = body.is_stock_holding

    if not set_clauses:
        raise HTTPException(status_code=400, detail="No fields to update")

    try:
        row = await db.execute(
            text(
                f"""
                UPDATE tenant_hierarchy_config
                SET {", ".join(set_clauses)}, updated_at = now()
                WHERE id = :id AND tenant_id = :tid
                RETURNING id, tenant_id, level_number, level_name, default_role_code,
                          role_display_label, is_stock_holding, is_active
                """
            ),
            params,
        )
    except IntegrityError as exc:
        # The uq_hierarchy_config_tenant_name constraint (migration 060) applies
        # here too — a rename to an already-used name must 422, not 500.
        if _is_duplicate_level_name_violation(exc):
            raise _duplicate_level_name_http_exception() from exc
        raise
    updated = row.fetchone()
    if not updated:
        raise HTTPException(status_code=404, detail="Hierarchy level not found")

    return SuccessResponse(
        data=HierarchyLevelOut(
            id=updated.id,
            tenant_id=updated.tenant_id,
            level_number=updated.level_number,
            level_name=updated.level_name,
            default_role_code=updated.default_role_code,
            role_display_label=updated.role_display_label,
            is_stock_holding=updated.is_stock_holding,
            is_active=updated.is_active,
        )
    )


class ApprovalCoverageResponse(BaseModel):
    transfer_rules_exist: bool
    transfer_level_covered: bool
    adj_rules_exist: bool
    adj_level_covered: bool
    self_approval_covered: bool
    transfer_level_perms_exist: bool


@router.get(
    "/{tenant_id}/approval-coverage",
    response_model=SuccessResponse[ApprovalCoverageResponse],
)
@require_permission(PERMISSIONS.TENANT_MANAGE)
async def get_approval_coverage(
    tenant_id: uuid.UUID,
    level: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[ApprovalCoverageResponse]:
    """Check whether a given hierarchy level has approval rule coverage.
    Called by the frontend after a new org node is created to determine
    whether to show a coverage warning banner."""
    tid = str(tenant_id)

    # 1. Transfer approval rules — any rules exist for this tenant?
    transfer_total = (
        await db.execute(
            text(
                "SELECT COUNT(*) FROM transfer_approval_rules "
                "WHERE tenant_id = :tid AND is_active = true"
            ),
            {"tid": tid},
        )
    ).scalar() or 0

    # 2. Transfer approval rules — does this level have coverage?
    # Covered if: any rule has source_level IS NULL AND dest_level IS NULL
    # (global catch-all), OR any rule explicitly mentions this level
    transfer_null_rule = (
        await db.execute(
            text(
                "SELECT COUNT(*) FROM transfer_approval_rules "
                "WHERE tenant_id = :tid AND is_active = true "
                "AND source_level IS NULL AND destination_level IS NULL"
            ),
            {"tid": tid},
        )
    ).scalar() or 0

    transfer_explicit = (
        await db.execute(
            text(
                "SELECT COUNT(*) FROM transfer_approval_rules "
                "WHERE tenant_id = :tid AND is_active = true "
                "AND (source_level = :lv OR destination_level = :lv)"
            ),
            {"tid": tid, "lv": level},
        )
    ).scalar() or 0

    transfer_level_covered = (transfer_null_rule > 0) or (transfer_explicit > 0)

    # 3. Adjustment approval rules
    adj_total = (
        await db.execute(
            text(
                "SELECT COUNT(*) FROM adjustment_approval_rules "
                "WHERE tenant_id = :tid AND is_active = true"
            ),
            {"tid": tid},
        )
    ).scalar() or 0

    adj_level = (
        await db.execute(
            text(
                "SELECT COUNT(*) FROM adjustment_approval_rules "
                "WHERE tenant_id = :tid AND is_active = true "
                "AND level_number = :lv"
            ),
            {"tid": tid, "lv": level},
        )
    ).scalar() or 0

    # 4. Self-approval policies
    self_appr = (
        await db.execute(
            text(
                "SELECT COUNT(*) FROM self_approval_policies "
                "WHERE tenant_id = :tid AND level_number = :lv"
            ),
            {"tid": tid, "lv": level},
        )
    ).scalar() or 0

    # 5. Transfer type level permissions
    level_perms = (
        await db.execute(
            text(
                "SELECT COUNT(*) FROM transfer_type_level_permissions ttlp "
                "JOIN transfer_type_config ttc ON ttc.id = ttlp.transfer_type_config_id "
                "WHERE ttc.tenant_id = :tid AND ttlp.level_number = :lv"
            ),
            {"tid": tid, "lv": level},
        )
    ).scalar() or 0

    return SuccessResponse(
        data=ApprovalCoverageResponse(
            transfer_rules_exist=transfer_total > 0,
            transfer_level_covered=transfer_level_covered,
            adj_rules_exist=adj_total > 0,
            adj_level_covered=adj_level > 0,
            self_approval_covered=self_appr > 0,
            transfer_level_perms_exist=level_perms > 0,
        )
    )


class CloneLevelPermsResponse(BaseModel):
    cloned: bool
    from_level: Optional[int]
    to_level: int
    transfer_types_updated: int


@router.post(
    "/{tenant_id}/nodes/{node_id}/clone-level-permissions",
    response_model=SuccessResponse[CloneLevelPermsResponse],
)
@require_permission(PERMISSIONS.TENANT_MANAGE)
async def clone_level_permissions(
    tenant_id: uuid.UUID,
    node_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[CloneLevelPermsResponse]:
    """Clone transfer_type_level_permissions from the highest existing
    level to this node's level. Idempotent — skips if row already exists."""
    tid = str(tenant_id)

    # Get this node's level
    node_row = (
        await db.execute(
            text(
                "SELECT hierarchy_level FROM organization_node "
                "WHERE id = :nid AND tenant_id = :tid AND is_active = true"
            ),
            {"nid": str(node_id), "tid": tid},
        )
    ).fetchone()
    if not node_row:
        raise HTTPException(status_code=404, detail="Node not found")
    target_level = node_row.hierarchy_level

    # Find highest existing level that has permissions rows
    source_row = (
        await db.execute(
            text(
                "SELECT ttlp.level_number, ttlp.can_initiate, ttlp.can_receive, "
                "       ttlp.transfer_type_config_id "
                "FROM transfer_type_level_permissions ttlp "
                "JOIN transfer_type_config ttc ON ttc.id = ttlp.transfer_type_config_id "
                "WHERE ttc.tenant_id = :tid "
                "AND ttlp.level_number < :lv "
                "ORDER BY ttlp.level_number DESC LIMIT 1"
            ),
            {"tid": tid, "lv": target_level},
        )
    ).fetchone()

    if not source_row:
        return SuccessResponse(
            data=CloneLevelPermsResponse(
                cloned=False,
                from_level=None,
                to_level=target_level,
                transfer_types_updated=0,
            )
        )

    from_level = source_row.level_number

    # Get all transfer_type_config_ids for this tenant
    tt_rows = (
        await db.execute(
            text("SELECT id FROM transfer_type_config WHERE tenant_id = :tid AND is_active = true"),
            {"tid": tid},
        )
    ).fetchall()

    cloned_count = 0
    for tt_row in tt_rows:
        ttc_id = str(tt_row.id)
        # Check if a row already exists for target_level on this transfer type
        exists = (
            await db.execute(
                text(
                    "SELECT 1 FROM transfer_type_level_permissions "
                    "WHERE transfer_type_config_id = :ttc AND level_number = :lv"
                ),
                {"ttc": ttc_id, "lv": target_level},
            )
        ).fetchone()
        if exists:
            continue

        # Get source level permissions for this transfer type
        src = (
            await db.execute(
                text(
                    "SELECT can_initiate, can_receive "
                    "FROM transfer_type_level_permissions "
                    "WHERE transfer_type_config_id = :ttc AND level_number = :src_lv"
                ),
                {"ttc": ttc_id, "src_lv": from_level},
            )
        ).fetchone()

        if src:
            await db.execute(
                text(
                    "INSERT INTO transfer_type_level_permissions "
                    "(tenant_id, transfer_type_config_id, level_number, can_initiate, can_receive) "
                    "VALUES (:tid, :ttc, :lv, :ci, :cr)"
                ),
                {
                    "tid": str(tenant_id),
                    "ttc": ttc_id,
                    "lv": target_level,
                    "ci": src.can_initiate,
                    "cr": src.can_receive,
                },
            )
            cloned_count += 1

    return SuccessResponse(
        data=CloneLevelPermsResponse(
            cloned=cloned_count > 0,
            from_level=from_level,
            to_level=target_level,
            transfer_types_updated=cloned_count,
        )
    )


@router.delete(
    "/{tenant_id}/hierarchy/config/reset",
    response_model=SuccessResponse[dict],
)
@require_permission(PERMISSIONS.TENANT_MANAGE)
async def reset_hierarchy_config(
    tenant_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[dict]:
    """SA-only escape hatch for the level-count lock (see G3a above). Clears a
    tenant's hierarchy config entirely so the TA can redefine it from scratch —
    only permitted while the tenant has no org nodes, since nodes reference a
    hierarchy_level that would otherwise become orphaned."""
    if user.role != "SA":
        raise HTTPException(
            status_code=403,
            detail={
                "code": "FORBIDDEN",
                "message": "Only a platform administrator (SA) may reset org level configuration.",
            },
        )

    node_count = (
        await db.execute(
            text(
                "SELECT COUNT(*) FROM organization_node WHERE tenant_id = :tid AND is_active = true"
            ),
            {"tid": str(tenant_id)},
        )
    ).scalar() or 0
    if node_count > 0:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "ORG_NODES_EXIST",
                "message": "Cannot reset org levels while org nodes exist. Remove all "
                "nodes first, then request a reset.",
            },
        )

    await db.execute(
        text("DELETE FROM tenant_hierarchy_config WHERE tenant_id = :tid"),
        {"tid": str(tenant_id)},
    )

    await audit_log(
        user,
        PERMISSIONS.TENANT_MANAGE.id,
        {
            "resource_type": "tenant_hierarchy_config",
            "resource_id": str(tenant_id),
            "tenant_id": str(tenant_id),
        },
        "GRANTED",
        "SA reset org level configuration for tenant",
        db=db,
    )

    return SuccessResponse(
        data={
            "reset": True,
            "message": "Org levels cleared. Tenant Admin can now redefine the org structure.",
        }
    )


# ── Org node endpoints ────────────────────────────────────────────────────────


@router.get(
    "/{tenant_id}/nodes",
    response_model=SuccessResponse[List[OrgNodeOut]],
)
@require_permission(PERMISSIONS.INVENTORY_VIEW)
async def list_org_nodes(
    tenant_id: uuid.UUID,
    include_inactive: bool = False,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[List[OrgNodeOut]]:
    # user_facility_assignments was dropped in migration 031.
    # Manager = the PRIMARY personnel_position holder at the node with the highest
    # authority role (NM > RM > WM = LM > …). LATERAL subquery returns at most one
    # manager per node, ordered by role authority descending.
    active_filter = "" if include_inactive else "AND n.is_active = true "
    rows = await db.execute(
        text(
            "SELECT n.id, n.tenant_id, n.name, n.code, n.hierarchy_level, n.parent_node_id, "
            "n.is_stock_holding, n.is_active, n.address, "
            "mgr.manager_name, mgr.manager_role "
            "FROM organization_node n "
            "LEFT JOIN LATERAL ("
            "  SELECT u.full_name AS manager_name, p.role_code AS manager_role "
            "  FROM positions p "
            "  JOIN personnel_positions pp "
            "    ON pp.position_id = p.id "
            "   AND pp.assignment_type = 'PRIMARY' "
            "   AND pp.is_active = true "
            "   AND (pp.valid_until IS NULL OR pp.valid_until >= CURRENT_DATE) "
            "  JOIN users u ON u.id = pp.user_id AND u.is_active = true "
            "  WHERE p.node_id = n.id AND p.tenant_id = n.tenant_id AND p.is_active = true "
            "  ORDER BY CASE p.role_code "
            "    WHEN 'NM' THEN 8 WHEN 'RM' THEN 7 WHEN 'LM' THEN 6 "
            "    WHEN 'WM' THEN 6 WHEN 'SA_GT' THEN 4 ELSE 0 END DESC "
            "  LIMIT 1"
            ") mgr ON true "
            "WHERE n.tenant_id = :tid " + active_filter + "ORDER BY n.hierarchy_level, n.name"
        ),
        {"tid": str(tenant_id)},
    )
    all_nodes = [
        {
            "id": r.id,
            "tenant_id": r.tenant_id,
            "name": r.name,
            "code": r.code,
            "hierarchy_level": r.hierarchy_level,
            "parent_node_id": r.parent_node_id,
            "is_stock_holding": r.is_stock_holding,
            "is_active": r.is_active,
            "address": getattr(r, "address", None),
            "manager_name": getattr(r, "manager_name", None),
            "manager_role": getattr(r, "manager_role", None),
        }
        for r in rows.fetchall()
    ]

    # Load level names once
    lvl_rows = await db.execute(
        text("SELECT level_number, level_name FROM tenant_hierarchy_config WHERE tenant_id = :tid"),
        {"tid": str(tenant_id)},
    )
    level_names = {r.level_number: r.level_name for r in lvl_rows.fetchall()}

    # Group by parent_node_id for tree assembly
    nodes_by_parent: dict[Optional[str], list[dict]] = {}
    for node in all_nodes:
        parent_key = str(node["parent_node_id"]) if node["parent_node_id"] else None
        nodes_by_parent.setdefault(parent_key, []).append(node)

    tree = await _build_tree(db, str(tenant_id), nodes_by_parent, level_names)
    return SuccessResponse(data=tree)


@router.post(
    "/{tenant_id}/nodes",
    status_code=201,
    response_model=SuccessResponse[OrgNodeOut],
)
@require_permission(PERMISSIONS.TENANT_MANAGE)
async def create_org_node(
    tenant_id: uuid.UUID,
    body: OrgNodeCreate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[OrgNodeOut]:
    if not (1 <= body.level_number <= 5):
        raise HTTPException(status_code=422, detail="level_number must be between 1 and 5")

    # Only a stock-holding node counts toward the plan cap — approval-only nodes are free.
    if body.is_stock_holding:
        await check_plan_create_warehouse(user, db)

    # Validate parent exists and belongs to same tenant when provided
    if body.parent_node_id:
        parent_row = await db.execute(
            text(
                "SELECT id FROM organization_node "
                "WHERE id = :pid AND tenant_id = :tid AND is_active = true"
            ),
            {"pid": str(body.parent_node_id), "tid": str(tenant_id)},
        )
        if not parent_row.fetchone():
            raise HTTPException(status_code=422, detail="parent_node_id not found in this tenant")

    code = _derive_code(str(tenant_id), body.name, body.level_number)
    node_id = uuid.uuid4()

    await db.execute(
        text(
            """
            INSERT INTO organization_node
                (id, tenant_id, name, code, hierarchy_level, parent_node_id,
                 is_stock_holding, address, is_active)
            VALUES (:id, :tid, :name, :code, :level, :parent, :stock, :address, true)
            """
        ),
        {
            "id": str(node_id),
            "tid": str(tenant_id),
            "name": body.name,
            "code": code,
            "level": body.level_number,
            "parent": str(body.parent_node_id) if body.parent_node_id else None,
            "stock": body.is_stock_holding,
            "address": body.address,
        },
    )

    # Auto-create PRIMARY_REPORTS_TO relationship when parent is supplied
    if body.parent_node_id:
        await db.execute(
            text(
                """
                INSERT INTO org_node_hierarchy
                    (tenant_id, from_node_id, to_node_id, relationship_type, is_preferred)
                VALUES (:tid, :from_id, :to_id, 'PRIMARY_REPORTS_TO', false)
                ON CONFLICT DO NOTHING
                """
            ),
            {
                "tid": str(tenant_id),
                "from_id": str(node_id),
                "to_id": str(body.parent_node_id),
            },
        )

    level_name = await _get_level_name(db, str(tenant_id), body.level_number)
    return SuccessResponse(
        data=OrgNodeOut(
            id=node_id,
            tenant_id=tenant_id,
            name=body.name,
            code=code,
            hierarchy_level=body.level_number,
            level_name=level_name,
            is_stock_holding=body.is_stock_holding,
            parent_node_id=body.parent_node_id,
            manager_name=None,
            manager_role=None,
            is_active=True,
            address=body.address,
        )
    )


@router.patch(
    "/{tenant_id}/nodes/{node_id}",
    response_model=SuccessResponse[OrgNodeOut],
)
@require_permission(PERMISSIONS.TENANT_MANAGE)
async def update_org_node(
    tenant_id: uuid.UUID,
    node_id: uuid.UUID,
    body: OrgNodeUpdate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[OrgNodeOut]:
    row = await db.execute(
        text(
            "SELECT id, tenant_id, name, code, hierarchy_level, parent_node_id, "
            "is_stock_holding, is_active, address "
            "FROM organization_node "
            "WHERE id = :id AND tenant_id = :tid AND is_active = true"
        ),
        {"id": str(node_id), "tid": str(tenant_id)},
    )
    existing = row.fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Node not found")

    new_name = body.name if body.name is not None else existing.name
    new_stock = (
        body.is_stock_holding if body.is_stock_holding is not None else existing.is_stock_holding
    )
    new_address = body.address if body.address is not None else getattr(existing, "address", None)

    if body.is_stock_holding is True:
        level_row = (
            await db.execute(
                text(
                    "SELECT is_stock_holding FROM tenant_hierarchy_config "
                    "WHERE tenant_id = :tid AND level_number = :lvl"
                ),
                {"tid": str(tenant_id), "lvl": existing.hierarchy_level},
            )
        ).fetchone()
        if level_row is not None and not level_row.is_stock_holding:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "LEVEL_DOES_NOT_HOLD_STOCK",
                    "message": "This level is not configured to hold stock. "
                    "Update the level configuration first.",
                },
            )

    if existing.is_stock_holding and body.is_stock_holding is False:
        blocker = await _node_stock_activity_blocker(db, str(tenant_id), str(node_id))
        if blocker:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "NODE_STOCK_ACTIVITY",
                    "reason": blocker["code"],
                    "message": "Move or issue the remaining stock and close open "
                    "transfers/adjustments before making this an "
                    "approval-only location.",
                },
            )

    # Flipping a node from approval-only to stock-holding counts toward the plan
    # cap the same as creating a new warehouse — close the flip loophole.
    if not existing.is_stock_holding and new_stock:
        await check_plan_create_warehouse(user, db)

    await db.execute(
        text(
            "UPDATE organization_node SET name = :name, is_stock_holding = :stock, "
            "address = :address, updated_at = now() "
            "WHERE id = :id AND tenant_id = :tid"
        ),
        {
            "name": new_name,
            "stock": new_stock,
            "address": new_address,
            "id": str(node_id),
            "tid": str(tenant_id),
        },
    )

    level_name = await _get_level_name(db, str(tenant_id), existing.hierarchy_level)
    manager_name, manager_role = await _node_manager(db, str(node_id), str(tenant_id))

    return SuccessResponse(
        data=OrgNodeOut(
            id=node_id,
            tenant_id=tenant_id,
            name=new_name,
            code=existing.code,
            address=new_address,
            hierarchy_level=existing.hierarchy_level,
            level_name=level_name,
            is_stock_holding=new_stock,
            parent_node_id=existing.parent_node_id,
            manager_name=manager_name,
            manager_role=manager_role,
            is_active=True,
        )
    )


@router.delete(
    "/{tenant_id}/nodes/{node_id}",
    response_model=SuccessResponse[dict],
)
@require_permission(PERMISSIONS.TENANT_MANAGE)
async def delete_org_node(
    tenant_id: uuid.UUID,
    node_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[dict]:
    row = await db.execute(
        text(
            "SELECT id FROM organization_node "
            "WHERE id = :id AND tenant_id = :tid AND is_active = true"
        ),
        {"id": str(node_id), "tid": str(tenant_id)},
    )
    if not row.fetchone():
        raise HTTPException(status_code=404, detail="Node not found")

    # Block deletion if the node holds live inventory
    balance_row = await db.execute(
        text(
            "SELECT COALESCE(SUM(quantity), 0) AS total "
            "FROM inventory_balances "
            "WHERE warehouse_id = :wid AND tenant_id = :tid"
        ),
        {"wid": str(node_id), "tid": str(tenant_id)},
    )
    total = balance_row.fetchone()
    if total and float(total.total) > 0:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "NODE_HAS_INVENTORY",
                "message": "Cannot delete a node that holds active inventory. "
                "Transfer or adjust stock to zero first.",
            },
        )

    # Block deletion if the node has active child nodes
    children_row = await db.execute(
        text(
            "SELECT COUNT(*) AS cnt FROM organization_node "
            "WHERE parent_node_id = :id AND tenant_id = :tid AND is_active = true"
        ),
        {"id": str(node_id), "tid": str(tenant_id)},
    )
    children = children_row.fetchone()
    if children and children.cnt > 0:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "NODE_HAS_CHILDREN",
                "message": "Cannot delete a node that has active child nodes.",
            },
        )

    await db.execute(
        text(
            "UPDATE organization_node SET is_active = false, updated_at = now() "
            "WHERE id = :id AND tenant_id = :tid"
        ),
        {"id": str(node_id), "tid": str(tenant_id)},
    )
    return SuccessResponse(data={"deleted": str(node_id)})


@router.patch(
    "/{tenant_id}/nodes/{node_id}/deactivate",
    response_model=SuccessResponse[dict],
)
@require_permission(PERMISSIONS.TENANT_MANAGE)
async def deactivate_org_node(
    tenant_id: uuid.UUID,
    node_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[dict]:
    row = await db.execute(
        text(
            "SELECT id FROM organization_node "
            "WHERE id = :id AND tenant_id = :tid AND is_active = true"
        ),
        {"id": str(node_id), "tid": str(tenant_id)},
    )
    if not row.fetchone():
        raise HTTPException(status_code=404, detail="Node not found")

    # CHECKS 1 & 2 — no open transfers, no pending adjustments
    blocker = await _node_stock_activity_blocker(
        db,
        str(tenant_id),
        str(node_id),
        checks=("transfers", "adjustments"),
    )
    if blocker:
        raise HTTPException(status_code=422, detail=blocker)

    # CHECK 3 — no users whose ONLY active position is at this node
    sole_row = await db.execute(
        text(
            """
            SELECT COUNT(DISTINCT pp.user_id) AS cnt
            FROM personnel_positions pp
            JOIN positions p ON p.id = pp.position_id
            WHERE pp.tenant_id = :tid
              AND pp.is_active = true
              AND (pp.valid_until IS NULL OR pp.valid_until >= CURRENT_DATE)
              AND p.node_id = :wid
              AND pp.user_id IN (
                  SELECT user_id FROM personnel_positions
                  WHERE tenant_id = :tid AND is_active = true
                    AND (valid_until IS NULL OR valid_until >= CURRENT_DATE)
                  GROUP BY user_id HAVING COUNT(*) = 1
              )
            """
        ),
        {"wid": str(node_id), "tid": str(tenant_id)},
    )
    sole_count = sole_row.fetchone()
    if sole_count and sole_count.cnt > 0:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "NODE_HAS_SOLE_USERS",
                "message": f"Cannot deactivate — {sole_count.cnt} staff member(s) have "
                "this as their only position. Reassign them to another "
                "position first.",
            },
        )

    # CHECK 4 — no stock on hand
    blocker = await _node_stock_activity_blocker(
        db,
        str(tenant_id),
        str(node_id),
        checks=("stock",),
    )
    if blocker:
        raise HTTPException(status_code=422, detail=blocker)

    await db.execute(
        text(
            "UPDATE organization_node SET is_active = false, updated_at = now() "
            "WHERE id = :id AND tenant_id = :tid"
        ),
        {"id": str(node_id), "tid": str(tenant_id)},
    )
    return SuccessResponse(data={"deactivated": str(node_id)})


@router.patch(
    "/{tenant_id}/nodes/{node_id}/reactivate",
    response_model=SuccessResponse[dict],
)
@require_permission(PERMISSIONS.TENANT_MANAGE)
async def reactivate_org_node(
    tenant_id: uuid.UUID,
    node_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[dict]:
    row = await db.execute(
        text(
            "SELECT id, hierarchy_level, is_stock_holding FROM organization_node "
            "WHERE id = :id AND tenant_id = :tid AND is_active = false"
        ),
        {"id": str(node_id), "tid": str(tenant_id)},
    )
    existing = row.fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Inactive node not found")

    # Reactivating a stock-holding node counts toward the plan cap the same as
    # creating one — approval-only nodes never count, at any level.
    if existing.is_stock_holding:
        await check_plan_create_warehouse(user, db)

    await db.execute(
        text(
            "UPDATE organization_node SET is_active = true, updated_at = now() "
            "WHERE id = :id AND tenant_id = :tid"
        ),
        {"id": str(node_id), "tid": str(tenant_id)},
    )
    return SuccessResponse(data={"reactivated": str(node_id)})


# ── Supply route endpoints ─────────────────────────────────────────────────────


@router.post(
    "/{tenant_id}/nodes/{node_id}/supply-routes",
    response_model=SuccessResponse[SupplyRouteOut],
)
@require_permission(PERMISSIONS.TENANT_MANAGE)
async def set_supply_routes(
    tenant_id: uuid.UUID,
    node_id: uuid.UUID,
    body: SupplyRouteIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[SupplyRouteOut]:
    # Verify node belongs to tenant
    row = await db.execute(
        text(
            "SELECT id FROM organization_node "
            "WHERE id = :id AND tenant_id = :tid AND is_active = true"
        ),
        {"id": str(node_id), "tid": str(tenant_id)},
    )
    if not row.fetchone():
        raise HTTPException(status_code=404, detail="Node not found")

    # Verify source nodes belong to same tenant
    for source_id in [body.primary_source_id, body.secondary_source_id]:
        if source_id is None:
            continue
        src_row = await db.execute(
            text(
                "SELECT id FROM organization_node "
                "WHERE id = :id AND tenant_id = :tid AND is_active = true"
            ),
            {"id": str(source_id), "tid": str(tenant_id)},
        )
        if not src_row.fetchone():
            raise HTTPException(
                status_code=422,
                detail=f"Source node {source_id} not found in this tenant",
            )

    # Remove existing SUPPLY_FROM relationships for this node
    await db.execute(
        text(
            "DELETE FROM org_node_hierarchy "
            "WHERE tenant_id = :tid AND from_node_id = :fid "
            "AND relationship_type = 'SUPPLY_FROM'"
        ),
        {"tid": str(tenant_id), "fid": str(node_id)},
    )

    # Insert primary source
    await db.execute(
        text(
            """
            INSERT INTO org_node_hierarchy
                (tenant_id, from_node_id, to_node_id, relationship_type, is_preferred)
            VALUES (:tid, :from_id, :to_id, 'SUPPLY_FROM', true)
            """
        ),
        {
            "tid": str(tenant_id),
            "from_id": str(node_id),
            "to_id": str(body.primary_source_id),
        },
    )

    # Insert secondary source (not preferred)
    if body.secondary_source_id:
        await db.execute(
            text(
                """
                INSERT INTO org_node_hierarchy
                    (tenant_id, from_node_id, to_node_id, relationship_type, is_preferred)
                VALUES (:tid, :from_id, :to_id, 'SUPPLY_FROM', false)
                """
            ),
            {
                "tid": str(tenant_id),
                "from_id": str(node_id),
                "to_id": str(body.secondary_source_id),
            },
        )

    return SuccessResponse(
        data=SupplyRouteOut(
            node_id=node_id,
            primary_source_id=body.primary_source_id,
            secondary_source_id=body.secondary_source_id,
        )
    )
