import functools
import inspect
import uuid
from typing import Any, Callable

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from shared.permissions.audit import audit_log
from shared.permissions.hierarchy_service import FACILITY_SCOPED_ROLES, get_descendant_node_ids
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

    # Path tenant_id check (RB-1 sweep HOLEs 1-3 root cause, docs/reviews/2026-10-19-rb1-sweep.md):
    # require_permission's wrapper stashes the route's own {tenant_id} path value as
    # target_tenant_id (distinct from the tautological "tenant_id" check above, which
    # the wrapper always sets to the caller's OWN tenant_id) — target_tenant_id is set
    # for ANY tenant_id kwarg (path or query override) so audit_log() can keep
    # attributing an SA's decision on an override route to the right tenant (session 17).
    # Enforcement below reads the SEPARATE "_tenant_id_from_path" flag, which the wrapper
    # only sets for a required {tenant_id} path segment — these two concerns must never
    # be entangled into one condition again. A non-SA/SYS caller whose path tenant_id
    # resolves (by UUID or by slug, case-insensitively) to a different tenant than their
    # own is denied here, regardless of whether the route handler checks this itself.
    target_tenant_id = resource.get("target_tenant_id")
    if target_tenant_id and resource.get("_tenant_id_from_path") and user.role not in ("SA", "SYS"):
        resolved_target: str | None
        try:
            uuid.UUID(str(target_tenant_id))
            resolved_target = str(target_tenant_id).lower()
        except ValueError:
            resolved_target = None
            if db is not None:
                from sqlalchemy import text as _sql_text

                row = (
                    await db.execute(
                        _sql_text("SELECT id FROM tenants WHERE slug = :slug"),
                        {"slug": str(target_tenant_id)},
                    )
                ).fetchone()
                if row is not None:
                    resolved_target = str(row.id).lower()
        if resolved_target is None or resolved_target != str(user.tenant_id).lower():
            await audit_log(
                user, action.id, resource, "DENIED", "ABAC_DENIED: TENANT_ACCESS_DENIED"
            )
            return PermissionResult(allowed=False, reason="TENANT_ACCESS_DENIED")

    if "region_id" in action.abac and getattr(user, "region_id", None):
        if resource.get("region_id") and resource["region_id"] != user.region_id:
            await audit_log(user, action.id, resource, "DENIED", "ABAC_DENIED: region scope")
            return PermissionResult(allowed=False, reason="ABAC_DENIED: region scope")

    # 4. Warehouse scope — node + descendant traversal for FACILITY_SCOPED_ROLES.
    # Fail closed (RB-2 G1): a facility-scoped user with no node gets an empty
    # scope, so any warehouse-scoped resource is denied.
    if user.role in FACILITY_SCOPED_ROLES:
        resource_wh = resource.get("warehouse_id")
        if resource_wh and "warehouse_id" in action.abac:
            resource_wh_str = str(resource_wh).lower()
            user_wh_str = str(user.warehouse_id or "").lower()
            # Check scope cache first
            if scope_cache is None:
                scope_cache = {}
            if user_wh_str not in scope_cache:
                if not user.warehouse_id:
                    scope_cache[user_wh_str] = set()
                elif db is not None:
                    scope_cache[user_wh_str] = {
                        n.lower()
                        for n in await get_descendant_node_ids(
                            db, str(user.tenant_id), str(user.warehouse_id)
                        )
                    }
                else:
                    # No db session available — fall back to exact match
                    scope_cache[user_wh_str] = {user_wh_str}
            if resource_wh_str not in scope_cache[user_wh_str]:
                await audit_log(user, action.id, resource, "DENIED", "ABAC_DENIED: warehouse scope")
                return PermissionResult(allowed=False, reason="ABAC_DENIED: warehouse scope")

    if grant.grant_type == "CONDITIONAL":
        await audit_log(user, action.id, resource, "CONDITIONAL", "APPROVAL_REQUIRED")
        return PermissionResult(allowed=True, condition="APPROVAL_REQUIRED")

    await audit_log(user, action.id, resource, "GRANTED")
    return PermissionResult(allowed=True)


def require_permission(
    action: Permission,
    read_only_exempt: bool = False,
    read_only_force_write: bool = False,
) -> Callable:
    """Decorator for FastAPI route handlers. Injects permission check before handler executes."""

    if read_only_exempt and read_only_force_write:
        raise ValueError(
            "require_permission: read_only_exempt and read_only_force_write are mutually exclusive"
        )

    def decorator(func: Callable) -> Callable:
        # Computed once per route, not per call: a route's `tenant_id` parameter
        # is a required {tenant_id} PATH segment only if it has no default value
        # (FastAPI path params can never have one). An Optional[...] = Query(None)
        # tenant_id is a caller-supplied override that routes already resolve via
        # effective_tenant_id() (ignored for non-SA) — that pattern must NOT be
        # subjected to the path-tenant_id mismatch check below, or a non-SA's
        # harmless/ignored override gets rejected instead of silently downgraded,
        # breaking existing, intended behaviour (e.g. GET .../expiry-settings?tenant_id=<other>).
        _sig = inspect.signature(func)
        _tenant_id_param = _sig.parameters.get("tenant_id")
        _tenant_id_is_required_path_param = bool(
            _tenant_id_param is not None and _tenant_id_param.default is inspect.Parameter.empty
        )

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

            # Stash the route's tenant_id kwarg (path OR optional query override)
            # separately from the actor's own tenant_id — an SA has no tenant_id of
            # its own, so this is how audit_log() attributes an SA's decision to the
            # tenant being acted on, for EITHER kind of route. Unconditional — must
            # not be narrowed to the required-path-param case (session 17 regression).
            path_tenant_id = kwargs.get("tenant_id")
            if path_tenant_id is not None and "target_tenant_id" not in resource:
                resource["target_tenant_id"] = str(path_tenant_id)
            # Separate flag: enforcement (in check_permission) only applies when this
            # tenant_id came from a REQUIRED {tenant_id} path segment, never from an
            # Optional[...] = Query(None) override — kept fully independent of the
            # audit-attribution assignment above.
            if path_tenant_id is not None and _tenant_id_is_required_path_param:
                resource["_tenant_id_from_path"] = True

            body = kwargs.get("body")
            if body and hasattr(body, "model_dump"):
                resource.update(body.model_dump(exclude_none=True))

            db = kwargs.get("db")
            _scope_cache: dict[str, set[str]] = {}

            result = await check_permission(user, action, resource, db=db, scope_cache=_scope_cache)

            if not result.allowed:
                raise HTTPException(
                    status_code=403,
                    detail={"code": result.reason, "action": action.id},
                )

            if user.role not in ("SA", "SYS") and getattr(user, "tenant_id", None):
                from shared.permissions.read_only import is_blocked_in_read_only

                if is_blocked_in_read_only(action.id, read_only_exempt, read_only_force_write):
                    if db is None:
                        raise HTTPException(
                            status_code=500,
                            detail={"code": "CONTRACT_CHECK_NO_DB", "action": action.id},
                        )

                    from shared.billing.contract_stage import get_tenant_contract_stage

                    contract = await get_tenant_contract_stage(db, str(user.tenant_id))
                    if contract["stage"] == "READ_ONLY":
                        raise HTTPException(
                            status_code=402,
                            detail={
                                "code": "CONTRACT_EXPIRED_READ_ONLY",
                                "action": action.id,
                                "contract_end": (
                                    contract["contract_end"].isoformat()
                                    if contract["contract_end"]
                                    else None
                                ),
                                "read_only_since": (
                                    contract["read_only_since"].isoformat()
                                    if contract["read_only_since"]
                                    else None
                                ),
                            },
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
