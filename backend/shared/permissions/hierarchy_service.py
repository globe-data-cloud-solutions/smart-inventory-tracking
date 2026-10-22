"""
Shared hierarchy traversal utility.
Used by check_permission() for node+descendant scope resolution.
Source of truth: organization_node.parent_node_id (flat FK, not org_node_hierarchy).
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

# Roles limited to their own node and the subtree below it (RB-2, 2026-10-22).
# RM is here: an RM is limited to its region for views and for warehouse actions.
FACILITY_SCOPED_ROLES = frozenset({"WM", "LM", "SA_GT", "RT", "RM"})
# LM Track B (business rule 25): an LM with no node assigned is tenant-wide.
# Every other facility-scoped role with no node fails closed.
NO_NODE_TENANT_WIDE_ROLES = frozenset({"LM"})
# Roles that see the whole tenant regardless of node.
TENANT_WIDE_ROLES = frozenset({"TA", "NM", "SA", "AU"})


async def get_descendant_node_ids(
    db: AsyncSession,
    tenant_id: str,
    node_id: str,
) -> set[str]:
    """
    Returns {node_id} union all active descendant node IDs,
    walking organization_node.parent_node_id recursively.

    Always includes the user's own node_id in the result set.
    Returns {node_id} (singleton) on any DB error — fail open
    to exact-match, never fail closed (do not raise).

    Inside check_permission() this is called only for FACILITY_SCOPED_ROLES.
    Outside it, it may also be used for RM subtree scoping in
    transfer_discrepancies (resolve and list); for those callers the
    fail-open {node_id} result is the stricter outcome (own node only).
    Never call this when node_id is None.
    """
    try:
        rows = await db.execute(
            text("""
                WITH RECURSIVE subtree AS (
                    SELECT id
                    FROM organization_node
                    WHERE id = :nid
                      AND tenant_id = :tid
                    UNION ALL
                    SELECT n.id
                    FROM organization_node n
                    INNER JOIN subtree s ON n.parent_node_id = s.id
                    WHERE n.tenant_id = :tid
                      AND n.is_active = true
                )
                SELECT id FROM subtree
            """),
            {"tid": tenant_id, "nid": node_id},
        )
        result = {str(r[0]) for r in rows.fetchall()}
        # Always include own node even if DB returns empty
        result.add(str(node_id))
        return result
    except Exception:
        # Fail open to exact-match — never block a user due to a
        # traversal error. Logged separately by the caller.
        return {str(node_id)}


async def resolve_node_scope(db: AsyncSession, user: Any) -> Optional[set[str]]:
    """Node ids a read should be filtered to, for the caller's level.

    None      tenant-wide (TA, NM, SA, AU): no filter.
    set[str]  lowercased node ids: the caller's node and its active descendants
              for FACILITY_SCOPED_ROLES; the node itself for any other role that
              has one.
    set()     fail closed: a facility-scoped caller with no node sees nothing.
    """
    role = getattr(user, "role", None)
    warehouse_id = getattr(user, "warehouse_id", None)
    if role in TENANT_WIDE_ROLES:
        return None
    if not warehouse_id:
        return None if role in NO_NODE_TENANT_WIDE_ROLES else set()
    if role in FACILITY_SCOPED_ROLES:
        nodes = await get_descendant_node_ids(db, str(user.tenant_id), str(warehouse_id))
        return {n.lower() for n in nodes}
    return {str(warehouse_id).lower()}
