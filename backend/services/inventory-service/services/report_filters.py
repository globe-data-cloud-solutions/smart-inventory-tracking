"""Report filters by hierarchy level, node (region or warehouse) and warehouse.

A filter can only narrow what the caller already sees. The route computes the
caller's scope (resolve_node_scope), computes the filter set here, and passes
the intersection to the report query. Reads run on the read replica.

Level numbers are the tenant's own: tenant_hierarchy_config names each level
and organization_node.hierarchy_level places each node on one. Nothing here
assumes "Region" is a fixed level number.
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.reports import LevelOption, NodeOption, ReportFilterOptions
from shared.permissions.hierarchy_service import get_descendant_node_ids


def _invalid(field: str) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": "INVALID_FILTER", "field": field})


def _uuid_or_422(value: Optional[str], field: str) -> Optional[str]:
    if value is None:
        return None
    try:
        return str(uuid.UUID(value)).lower()
    except ValueError as exc:
        raise _invalid(field) from exc


def intersect_scopes(a: Optional[set[str]], b: Optional[set[str]]) -> Optional[set[str]]:
    """None means no restriction. Intersecting with a filter can only narrow."""
    if a is None:
        return b
    if b is None:
        return a
    return a & b


async def _node_is_at_level(db: AsyncSession, tenant_id: str, node_id: str, level: int) -> bool:
    row = (
        await db.execute(
            text(
                """
                SELECT 1 FROM organization_node
                WHERE id = :nid AND tenant_id = :tid AND hierarchy_level = :lvl
                """
            ),
            {"nid": node_id, "tid": tenant_id, "lvl": level},
        )
    ).first()
    return row is not None


async def filter_scope(
    db: AsyncSession,
    tenant_id: str,
    level: Optional[int],
    node_id: Optional[str],
    warehouse_id: Optional[str],
) -> Optional[set[str]]:
    """The set of warehouse ids the filters select, or None when no filter is set.

    node_id selects that node and every node below it (a region, or a
    warehouse with nothing under it). warehouse_id selects one warehouse. When
    both are given the result is their intersection. level, when given, must
    be the level node_id sits on.
    """
    node = _uuid_or_422(node_id, "node_id")
    wh = _uuid_or_422(warehouse_id, "warehouse_id")
    if level is not None:
        if node is None:
            raise _invalid("level")
        if not await _node_is_at_level(db, tenant_id, node, level):
            raise _invalid("node_id")

    result: Optional[set[str]] = None
    if node is not None:
        subtree = await get_descendant_node_ids(db, tenant_id, node)
        result = {n.lower() for n in subtree}
    if wh is not None:
        result = intersect_scopes(result, {wh})
    return result


async def filter_options(
    db: AsyncSession, tenant_id: str, scope: Optional[set[str]]
) -> ReportFilterOptions:
    """Level names, and the active nodes the caller may pick a filter from."""
    level_rows = (
        await db.execute(
            text(
                """
                SELECT level_number, level_name FROM tenant_hierarchy_config
                WHERE tenant_id = :tid ORDER BY level_number
                """
            ),
            {"tid": tenant_id},
        )
    ).all()
    node_rows = (
        await db.execute(
            text(
                """
                SELECT id, name, code, hierarchy_level, parent_node_id
                FROM organization_node
                WHERE tenant_id = :tid AND is_active = true
                ORDER BY hierarchy_level, name
                """
            ),
            {"tid": tenant_id},
        )
    ).all()

    nodes: list[NodeOption] = []
    for r in node_rows:
        if scope is not None and str(r.id).lower() not in scope:
            continue
        nodes.append(
            NodeOption(
                id=r.id,
                name=r.name,
                code=r.code,
                hierarchy_level=r.hierarchy_level,
                parent_node_id=r.parent_node_id,
            )
        )
    levels = [LevelOption(level_number=r.level_number, level_name=r.level_name) for r in level_rows]
    return ReportFilterOptions(levels=levels, nodes=nodes)


__all__ = ["filter_options", "filter_scope", "intersect_scopes"]
