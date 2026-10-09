from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import text

from shared.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def audit_log(
    user: Any,
    action: str,
    resource: dict[str, Any],
    decision: str,
    reason: str = "",
) -> None:
    """Append-only write to audit_logs. Never raises — log failures must not break the request.

    audit_logs.tenant_id is NOT NULL. An SA actor has no tenant_id of their own, so a
    decision is attributed to (in priority order): the actor's own tenant_id, the
    resource's tenant_id, or the PATH tenant_id of the route being acted on (stashed by
    require_permission() as resource["target_tenant_id"] when the route has one). When
    none of those resolve — a platform-wide SA action such as tier-config — the decision
    is NOT inserted (there is no tenant to attach it to); it is logged as a warning
    instead. platform_config_log is the durable record for those platform-level changes.
    """
    tenant_id = (
        getattr(user, "tenant_id", None)
        or resource.get("tenant_id")
        or resource.get("target_tenant_id")
    )
    if tenant_id is None:
        logger.warning(
            "audit: platform-level decision not stored action=%s user=%s decision=%s",
            action, getattr(user, "user_id", None), decision,
        )
        return

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(
                text(
                    "INSERT INTO audit_logs "
                    "(id, tenant_id, user_id, role, action, resource_type, resource_id, "
                    " decision, reason, abac_context) "
                    "VALUES (:id, :tenant_id, :user_id, :role, :action, :resource_type, "
                    "        :resource_id, :decision, :reason, CAST(:abac_context AS jsonb))"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "tenant_id": str(tenant_id),
                    "user_id": getattr(user, "user_id", None),
                    "role": getattr(user, "role", None),
                    "action": action,
                    "resource_type": resource.get("resource_type"),
                    "resource_id": resource.get("resource_id"),
                    "decision": decision,
                    "reason": reason or None,
                    "abac_context": __import__("json").dumps(resource, default=str),
                },
            )
            await session.commit()
    except Exception:
        logger.exception(
            "audit: failed to write audit_logs row action=%s user=%s decision=%s",
            action, getattr(user, "user_id", None), decision,
        )
