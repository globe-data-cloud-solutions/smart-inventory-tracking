from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_db_session, get_current_user
from shared.permissions.hierarchy_service import get_descendant_node_ids
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse
from schemas.inventory import AuditLogItem

router = APIRouter()

# Roles with tenant-wide audit visibility — no warehouse scope filter applied.
# AU (Auditor) is included explicitly: previously AU had no warehouse_id, so it
# fell through to tenant-wide by accident (apply_scope required warehouse_id
# is not None). Listing it here makes that intentional and documented.
_TENANT_WIDE_ROLES = frozenset({"NM", "TA", "SA", "AU"})

# Appended to WHERE when scoping to a facility and its children.
# Covers: own actions, transfers where the facility is source or destination,
# and adjustments posted against the facility.
# :node_ids is bound as an expanding param — the facility + descendant ID set
# is resolved in Python via get_descendant_node_ids() before this query runs.
_SCOPE_CLAUSE = """
AND (
    al.user_id = :scope_uid
    OR al.resource_id IN (
        SELECT id FROM transfer_orders
        WHERE tenant_id = :tid
          AND (
            from_warehouse_id IN :node_ids
            OR to_warehouse_id IN :node_ids
          )
    )
    OR al.resource_id IN (
        SELECT id FROM adjustment_orders
        WHERE tenant_id = :tid
          AND warehouse_id IN :node_ids
    )
)
"""


@router.get("/", response_model=SuccessResponse[List[AuditLogItem]])
@require_permission(PERMISSIONS.AUDIT_VIEW_LOGS)
async def list_audit_logs(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    action: str = Query(None),
    resource_type: str = Query(None),
    include_system: bool = Query(False,
                                 description="Include SYSTEM-category actions (anything "
                                             "outside transfer:*, inventory:*, adjustment:*) "
                                             "and *:view / *:list read actions. Default false "
                                             "hides notifications, page views, and other "
                                             "system/read activity."),
    scope: str = Query("auto",
                       description="'auto' applies role-based scoping. "
                                   "'all' shows the entire tenant log (NM/TA/SA/AU only)."),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[List[AuditLogItem]]:
    params: dict = {
        "tid": str(user.tenant_id),
        "limit": limit,
        "offset": (page - 1) * limit,
    }

    # Determine whether to apply facility-level scoping.
    # NM/TA/SA/AU always see the full tenant log; scope=all is a no-op for them.
    # WM/RM/LM are always facility-scoped — scope=all is ignored to prevent
    # privilege escalation via query parameter.
    apply_scope = (
        user.role not in _TENANT_WIDE_ROLES
        and user.warehouse_id is not None
    )

    # Resolve facility + descendant node IDs only when scoping is active.
    if apply_scope:
        params["scope_uid"] = str(user.user_id)
        params["node_ids"] = sorted(await get_descendant_node_ids(
            db, str(user.tenant_id), str(user.warehouse_id)
        ))
        scope_fragment = _SCOPE_CLAUSE
    else:
        scope_fragment = ""

    where_parts = ["al.tenant_id = :tid"]
    if action:
        where_parts.append("al.action = :action")
        params["action"] = action
    if resource_type:
        where_parts.append("al.resource_type = :rtype")
        params["rtype"] = resource_type
    if not include_system:
        where_parts.append(
            "(al.action LIKE :transfer_pfx "
            "OR al.action LIKE :inventory_pfx "
            "OR al.action LIKE :adjustment_pfx)"
        )
        params["transfer_pfx"] = "transfer:%"
        params["inventory_pfx"] = "inventory:%"
        params["adjustment_pfx"] = "adjustment:%"
        # Hide read-only actions (e.g. transfer:list, transfer:view,
        # inventory:view_balance) regardless of category — same suffix/
        # substring noise the old include_views filter hid.
        where_parts.append("al.action NOT LIKE :view_pattern")
        where_parts.append("al.action NOT LIKE :list_pattern")
        params["view_pattern"] = "%:view%"
        params["list_pattern"] = "%:list%"

    where_clause = " AND ".join(where_parts)

    query = (
        f"SELECT al.id, al.timestamp, al.user_id, al.role, al.action, "
        f"       al.resource_type, al.resource_id, al.decision, al.reason, al.abac_context, "
        f"       u.full_name AS user_name, "
        f"       t_ord.transfer_type AS transfer_type, "
        f"       from_node.name AS from_warehouse_name, "
        f"       to_node.name AS to_warehouse_name, "
        f"       a_ord.reason_code AS adjustment_reason_code, "
        f"       COALESCE( "
        f"           (SELECT CASE WHEN COUNT(*) > 1 "
        f"                        THEN COUNT(*) || ' items' "
        f"                        ELSE MAX(p.name) || ' (' || "
        f"                             trim(trailing '.' from trim(trailing '0' from MAX(tol.quantity)::text)) "
        f"                             || ')' END "
        f"            FROM transfer_order_lines tol "
        f"            JOIN products p ON p.id = tol.product_id "
        f"            WHERE tol.transfer_order_id = t_ord.id), "
        f"           CASE WHEN a_ord.id IS NOT NULL "
        f"                THEN adj_p.name || ' (' || "
        f"                     trim(trailing '.' from trim(trailing '0' from a_ord.quantity_delta::text)) "
        f"                     || ')' "
        f"                ELSE NULL END "
        f"       ) AS product_summary "
        f"FROM audit_logs al "
        f"LEFT JOIN users u ON u.id = al.user_id "
        f"LEFT JOIN transfer_orders t_ord ON al.resource_type = 'transfer' AND al.resource_id = t_ord.id "
        f"LEFT JOIN adjustment_orders a_ord ON al.resource_type = 'adjustment' AND al.resource_id = a_ord.id "
        f"LEFT JOIN organization_node from_node ON from_node.id = t_ord.from_warehouse_id "
        f"LEFT JOIN organization_node to_node ON to_node.id = t_ord.to_warehouse_id "
        f"LEFT JOIN products adj_p ON adj_p.id = a_ord.product_id "
        f"WHERE {where_clause} "
        f"{scope_fragment}"
        f"ORDER BY al.timestamp DESC "
        f"LIMIT :limit OFFSET :offset"
    )

    stmt = text(query)
    if apply_scope:
        stmt = stmt.bindparams(bindparam("node_ids", expanding=True))
    rows = (await db.execute(stmt, params)).fetchall()

    return SuccessResponse(data=[
        AuditLogItem(
            id=r.id,
            timestamp=r.timestamp,
            user_id=r.user_id,
            user_name=r.user_name,
            role=r.role,
            action=r.action,
            resource_type=r.resource_type,
            resource_id=r.resource_id,
            decision=r.decision,
            reason=r.reason,
            abac_context=r.abac_context,
            transfer_type=r.transfer_type,
            from_warehouse_name=r.from_warehouse_name,
            to_warehouse_name=r.to_warehouse_name,
            product_summary=r.product_summary,
            adjustment_reason_code=r.adjustment_reason_code,
        )
        for r in rows
    ])
