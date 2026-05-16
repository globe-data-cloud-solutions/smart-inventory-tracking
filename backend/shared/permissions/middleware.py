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
        # Only enforce when the resource carries a specific warehouse_id — actions that
        # don't supply one (e.g. list endpoints) are still allowed.  When a warehouse_id
        # IS present in the resource, the user must have a matching assignment; a None
        # warehouse_id (middle-layer manager) never satisfies a warehouse scope check.
        if resource_wh and (not user_wh or str(user_wh) != str(resource_wh)):
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
