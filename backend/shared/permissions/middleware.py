import functools
from typing import Any, Callable

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from shared.permissions.audit import audit_log
from shared.permissions.hierarchy_service import get_descendant_node_ids
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
    db: AsyncSession | None = None,
    scope_cache: dict[str, set[str]] | None = None,
) -> PermissionResult:
    if resource is None:
        resource = {}

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

    # 4. Warehouse scope — node + descendant traversal for FACILITY_SCOPED_ROLES
    FACILITY_SCOPED_ROLES = {"WM", "LM", "SA_GT", "RT"}
    if user.role in FACILITY_SCOPED_ROLES and user.warehouse_id:
        resource_wh = resource.get("warehouse_id")
        if resource_wh and "warehouse_id" in action.abac:
            resource_wh_str = str(resource_wh).lower()
            user_wh_str = str(user.warehouse_id).lower()
            # Check scope cache first
            if scope_cache is None:
                scope_cache = {}
            if user_wh_str not in scope_cache:
                if db is not None:
                    scope_cache[user_wh_str] = {
                        n.lower() for n in await get_descendant_node_ids(
                            db, str(user.tenant_id), str(user.warehouse_id)
                        )
                    }
                else:
                    # No db session available — fall back to exact match
                    scope_cache[user_wh_str] = {user_wh_str}
            if resource_wh_str not in scope_cache[user_wh_str]:
                await audit_log(user, action.id, resource, "DENIED",
                                "ABAC_DENIED: warehouse scope")
                return PermissionResult(allowed=False,
                                        reason="ABAC_DENIED: warehouse scope")

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

            # Stash the route's PATH tenant_id (e.g. /{tenant_id}/plan) separately from
            # the actor's own tenant_id — an SA has no tenant_id of its own, so this is
            # how audit_log() attributes an SA decision to the tenant being acted on.
            path_tenant_id = kwargs.get("tenant_id")
            if path_tenant_id is not None and "target_tenant_id" not in resource:
                resource["target_tenant_id"] = str(path_tenant_id)

            body = kwargs.get("body")
            if body and hasattr(body, "model_dump"):
                resource.update(body.model_dump(exclude_none=True))

            db = kwargs.get("db")
            _scope_cache: dict[str, set[str]] = {}

            result = await check_permission(user, action, resource, db=db,
                                            scope_cache=_scope_cache)

            if not result.allowed:
                raise HTTPException(
                    status_code=403,
                    detail={"code": result.reason, "action": action.id},
                )

            from shared.permissions.plan_middleware import check_plan, requires_flag

            if requires_flag(action.id):
                if db is None:
                    raise HTTPException(
                        status_code=500,
                        detail={"code": "PLAN_CHECK_NO_DB", "action": action.id},
                    )
                await check_plan(user, action.id, db)

            return await func(*args, **kwargs)

        wrapper.__permission__ = action  # type: ignore[attr-defined]
        return wrapper

    return decorator
