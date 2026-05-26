"""Org hierarchy and org node management endpoints.

Hierarchy config:   GET/PUT /tenants/{tenant_id}/hierarchy/config
Org node CRUD:      GET/POST /tenants/{tenant_id}/nodes
                    PATCH/DELETE /tenants/{tenant_id}/nodes/{node_id}
Supply routes:      POST /tenants/{tenant_id}/nodes/{node_id}/supply-routes
"""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_current_user, get_db_session
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse

router = APIRouter()


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


class OrgNodeCreate(BaseModel):
    name: str
    level_number: int
    parent_node_id: Optional[uuid.UUID] = None
    is_stock_holding: bool = True
    address: Optional[str] = None
    manager_user_id: Optional[uuid.UUID] = None


class OrgNodeUpdate(BaseModel):
    name: Optional[str] = None
    is_stock_holding: Optional[bool] = None
    address: Optional[str] = None
    manager_user_id: Optional[uuid.UUID] = None


class OrgNodeOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    code: str
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

async def _get_level_name(
    db: AsyncSession, tenant_id: str, level_number: int
) -> Optional[str]:
    row = await db.execute(
        text(
            "SELECT level_name FROM tenant_hierarchy_config "
            "WHERE tenant_id = :tid AND level_number = :lvl"
        ),
        {"tid": tenant_id, "lvl": level_number},
    )
    r = row.fetchone()
    return r[0] if r else None


async def _get_manager_info(
    db: AsyncSession, user_id: Optional[str]
) -> tuple[Optional[str], Optional[str]]:
    if not user_id:
        return None, None
    row = await db.execute(
        text("SELECT full_name, role FROM users WHERE id = :uid"),
        {"uid": user_id},
    )
    r = row.fetchone()
    return (r[0], r[1]) if r else (None, None)


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
        manager_name, manager_role = await _get_manager_info(db, node.get("manager_user_id"))
        result.append(
            OrgNodeOut(
                id=node["id"],
                tenant_id=node["tenant_id"],
                name=node["name"],
                code=node["code"],
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


# ── Hierarchy config endpoints ─────────────────────────────────────────────────

@router.get(
    "/{tenant_id}/hierarchy/config",
    response_model=SuccessResponse[List[HierarchyLevelOut]],
)
@require_permission(PERMISSIONS.TENANT_VIEW)
async def get_hierarchy_config(
    tenant_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[List[HierarchyLevelOut]]:
    rows = await db.execute(
        text(
            "SELECT id, tenant_id, level_number, level_name, default_role_code, "
            "role_display_label, is_stock_holding, is_active "
            "FROM tenant_hierarchy_config "
            "WHERE tenant_id = :tid ORDER BY level_number"
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
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[List[HierarchyLevelOut]]:
    if not body:
        raise HTTPException(status_code=400, detail="At least one level is required")
    for level in body:
        if not (1 <= level.level_number <= 5):
            raise HTTPException(
                status_code=422,
                detail=f"level_number must be between 1 and 5, got {level.level_number}",
            )

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

    rows = await db.execute(
        text(
            "SELECT id, tenant_id, level_number, level_name, default_role_code, "
            "role_display_label, is_stock_holding, is_active "
            "FROM tenant_hierarchy_config "
            "WHERE tenant_id = :tid ORDER BY level_number"
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
        )
        for r in rows.fetchall()
    ]
    return SuccessResponse(data=levels)


# ── Org node endpoints ────────────────────────────────────────────────────────

@router.get(
    "/{tenant_id}/nodes",
    response_model=SuccessResponse[List[OrgNodeOut]],
)
@require_permission(PERMISSIONS.TENANT_VIEW)
async def list_org_nodes(
    tenant_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[List[OrgNodeOut]]:
    rows = await db.execute(
        text(
            "SELECT id, tenant_id, name, code, hierarchy_level, parent_node_id, "
            "is_stock_holding, is_active "
            "FROM organization_node "
            "WHERE tenant_id = :tid AND is_active = true "
            "ORDER BY hierarchy_level, name"
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
            "manager_user_id": None,
        }
        for r in rows.fetchall()
    ]

    # Load level names once
    lvl_rows = await db.execute(
        text(
            "SELECT level_number, level_name FROM tenant_hierarchy_config "
            "WHERE tenant_id = :tid"
        ),
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
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[OrgNodeOut]:
    if not (1 <= body.level_number <= 5):
        raise HTTPException(status_code=422, detail="level_number must be between 1 and 5")

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
                 is_stock_holding, is_active)
            VALUES (:id, :tid, :name, :code, :level, :parent, :stock, true)
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
    manager_name, manager_role = await _get_manager_info(
        db, str(body.manager_user_id) if body.manager_user_id else None
    )

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
            manager_name=manager_name,
            manager_role=manager_role,
            is_active=True,
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
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[OrgNodeOut]:
    row = await db.execute(
        text(
            "SELECT id, tenant_id, name, code, hierarchy_level, parent_node_id, "
            "is_stock_holding, is_active "
            "FROM organization_node "
            "WHERE id = :id AND tenant_id = :tid AND is_active = true"
        ),
        {"id": str(node_id), "tid": str(tenant_id)},
    )
    existing = row.fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Node not found")

    new_name = body.name if body.name is not None else existing.name
    new_stock = body.is_stock_holding if body.is_stock_holding is not None else existing.is_stock_holding

    await db.execute(
        text(
            "UPDATE organization_node SET name = :name, is_stock_holding = :stock, "
            "updated_at = now() "
            "WHERE id = :id AND tenant_id = :tid"
        ),
        {
            "name": new_name,
            "stock": new_stock,
            "id": str(node_id),
            "tid": str(tenant_id),
        },
    )

    level_name = await _get_level_name(db, str(tenant_id), existing.hierarchy_level)
    manager_name, manager_role = await _get_manager_info(
        db, str(body.manager_user_id) if body.manager_user_id else None
    )

    return SuccessResponse(
        data=OrgNodeOut(
            id=node_id,
            tenant_id=tenant_id,
            name=new_name,
            code=existing.code,
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
    db: AsyncSession = Depends(get_db_session),
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
    db: AsyncSession = Depends(get_db_session),
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
