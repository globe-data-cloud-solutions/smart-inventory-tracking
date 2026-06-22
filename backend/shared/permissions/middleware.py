import functools
from typing import Any, Callable

from fastapi import HTTPException, Request

from shared.permissions.audit import audit_log
from shared.permissions.registry import Permission
from shared.permissions.store import get_role_permission


class PermissionResult:
    def __init__(
        self,
        allowed: bool,
        reason: str = "",
        condition: str | None = None,
    ) -> None:
        self.allowed = allowed
        self.reason = reason
        self.condition = condition


async def check_permission(
    user: Any,
    action: Permission,
    resource: dict[str, Any] | None = None,
) -> PermissionResult:
    resource = resource or {}

    grant = await get_role_permission(user.role, action.id)
    if not grant:
        await audit_log(user, action.id, resource, "DENIED", "RBAC_DENIED")
        return PermissionResult(allowed=False, reason="RBAC_DENIED")

    if "platform_only" in action.abac and user.role not in ("SA",):
        await audit_log(user, action.id, resource, "DENIED", "ABAC_DENIED: platform_only")
        return PermissionResult(allowed=False, reason="ABAC_DENIED: platform_only")

    if "system_only" in action.abac and user.role != "SYS":
        await audit_log(user, action.id, resource, "DENIED", "ABAC_DENIED: system_only")
        return PermissionResult(allowed=False, reason="ABAC_DENIED: system_only")

    if resource.get("tenant_id") and resource["tenant_id"] != user.tenant_id:
        if user.role != "SA":
            await audit_log(user, action.id, resource, "DENIED", "ABAC_DENIED: tenant mismatch")
            return PermissionResult(allowed=False, reason="ABAC_DENIED: tenant mismatch")

    if "region_id" in action.abac and getattr(user, "region_id", None):
        if resource.get("region_id") and resource["region_id"] != user.region_id:
            await audit_log(user, action.id, resource, "DENIED", "ABAC_DENIED: region scope")
            return PermissionResult(allowed=False, reason="ABAC_DENIED: region scope")

    if "warehouse_id" in action.abac:
        user_wh = getattr(user, "warehouse_id", None)
        resource_wh = resource.get("warehouse_id")
        # Warehouse scope is enforced for facility-scoped roles (WM, LM, SA_GT, RT).
        # Management roles (TA, NM, RM, AU, SA) operate across warehouses within
        # their authority — their warehouse_id JWT claim is a home facility, not a cage.
        #
        # LM was added here per design decision: LM should be node-scoped like WM,
        # not tenant-wide. A node-assigned LM's warehouse_id JWT claim is the node
        # their position belongs to (same mechanism as WM — see auth.py's
        # _lookup_user_with_position). A tenant-wide LM (system_role="LM", no
        # position) has warehouse_id=None, so user_wh is falsy and this check is
        # skipped entirely — that account type intentionally keeps tenant-wide
        # access, since there is no node to scope it to.
        #
        # TODO(scope-gap): this is an EXACT node match only (user_wh == resource_wh),
        # not "node + all descendant nodes" — there is no live ancestry-walking
        # implementation. get_authority_scope(), which would compute a node's full
        # descendant subtree via org_node_hierarchy, exists only in archived dead
        # code (_ARCHIVED_personnel_pre031.py) and was never wired into this
        # function. Implementing true descendant-scoping here would require adding
        # a db session parameter to check_permission() and every call site across
        # all services — out of scope for this fix. Applies equally to WM, SA_GT,
        # RT, and LM today: each sees only their own exact assigned node, not
        # subordinate nodes beneath it.
        FACILITY_SCOPED_ROLES = {"WM", "LM", "SA_GT", "RT"}
        if user.role in FACILITY_SCOPED_ROLES and user_wh and resource_wh and \
                str(user_wh).lower() != str(resource_wh).lower():
            await audit_log(user, action.id, resource, "DENIED", "ABAC_DENIED: warehouse scope")
            return PermissionResult(allowed=False, reason="ABAC_DENIED: warehouse scope")

    if grant.grant_type == "CONDITIONAL":
        await audit_log(user, action.id, resource, "CONDITIONAL", "APPROVAL_REQUIRED")
        return PermissionResult(allowed=True, condition="APPROVAL_REQUIRED")

    await audit_log(user, action.id, resource, "GRANTED")
    return PermissionResult(allowed=True)


def require_permission(action: Permission) -> Callable:
    """Decorator for FastAPI route handlers. Injects permission check before handler executes."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            user = kwargs.get("user") or (args[0] if args else None)
            if user is None:
                raise HTTPException(status_code=401, detail="Unauthenticated")

            resource = {
                "tenant_id": getattr(user, "tenant_id", None),
                "warehouse_id": kwargs.get("warehouse_id"),
                "region_id": getattr(user, "region_id", None),
            }

            body = kwargs.get("body")
            if body and hasattr(body, "model_dump"):
                resource.update(body.model_dump(exclude_none=True))

            result = await check_permission(user, action, resource)

            if not result.allowed:
                raise HTTPException(
                    status_code=403,
                    detail={"code": result.reason, "action": action.id},
                )

            return await func(*args, **kwargs)

        wrapper.__permission__ = action  # type: ignore[attr-defined]
        return wrapper

    return decorator
