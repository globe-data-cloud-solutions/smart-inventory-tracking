from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def audit_log(
    user: Any,
    action: str,
    resource: dict[str, Any],
    decision: str,
    reason: str = "",
    *,
    db: AsyncSession | None = None,
) -> None:
    """Append-only write to audit_logs, in one of two modes.

    Separate-session mode (db is None, the default): the row is written on its own
    AsyncSessionLocal session and committed immediately; failures are logged and
    swallowed — this call never raises. The permission middleware (shared/permissions/
    middleware.py) uses this mode on purpose: a DENIED/CONDITIONAL decision must be
    recorded even though the request's own transaction is about to roll back or never
    start, and an audit failure must not turn a permission decision into a 500.

    Caller-transaction mode (db given): the same INSERT runs on the caller's session,
    which is NOT committed here, and exceptions propagate. The audit row therefore
    commits or rolls back together with the business write it describes, so a
    business action can never be recorded without having happened (or vice versa).

    audit_logs.tenant_id is NOT NULL. An SA actor has no tenant_id of their own, so a
    decision is attributed to (in priority order): the actor's own tenant_id, the
    resource's tenant_id, or the PATH tenant_id of the route being acted on (stashed by
    require_permission() as resource["target_tenant_id"] when the route has one). When
    none of those resolve — a platform-wide SA action such as tier-config — the decision
    is NOT inserted (there is no tenant to attach it to); it is logged as a warning
    instead, in both modes. platform_config_log is the durable record for those
    platform-level changes.
    """
    tenant_id = (
        getattr(user, "tenant_id", None)
        or resource.get("tenant_id")
        or resource.get("target_tenant_id")
    )
    if tenant_id is None:
        logger.warning(
            "audit: platform-level decision not stored action=%s user=%s decision=%s",
            action,
            getattr(user, "user_id", None),
            decision,
        )
        return

    stmt = text(
        "INSERT INTO audit_logs "
        "(id, tenant_id, user_id, role, action, resource_type, resource_id, "
        " decision, reason, abac_context) "
        "VALUES (:id, :tenant_id, :user_id, :role, :action, :resource_type, "
        "        :resource_id, :decision, :reason, CAST(:abac_context AS jsonb))"
    )
    params = {
        "id": str(uuid.uuid4()),
        "tenant_id": str(tenant_id),
        "user_id": getattr(user, "user_id", None),
        "role": getattr(user, "role", None),
        "action": action,
        "resource_type": resource.get("resource_type"),
        "resource_id": resource.get("resource_id"),
        "decision": decision,
        "reason": reason or None,
        "abac_context": json.dumps(resource, default=str),
    }

    if db is not None:
        await db.execute(stmt, params)
        return

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(stmt, params)
            await session.commit()
    except Exception:
        logger.exception(
            "audit: failed to write audit_logs row action=%s user=%s decision=%s",
            action,
            getattr(user, "user_id", None),
            decision,
        )
