"""
Shared hierarchy traversal utility.
Used by check_permission() for node+descendant scope resolution.
Source of truth: organization_node.parent_node_id (flat FK, not org_node_hierarchy).
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text


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
