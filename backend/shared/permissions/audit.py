from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text

from shared.db.session import AsyncSessionLocal


async def audit_log(
    user: Any,
    action: str,
    resource: dict[str, Any],
    decision: str,
    reason: str = "",
) -> None:
    """Append-only write to audit_logs. Never raises — log failures must not break the request."""
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
                    "tenant_id": getattr(user, "tenant_id", None),
                    "user_id": getattr(user, "user_id", None),
                    "role": getattr(user, "role", None),
                    "action": action,
                    "resource_type": resource.get("resource_type"),
                    "resource_id": resource.get("resource_id"),
                    "decision": decision,
                    "reason": reason or None,
                    "abac_context": __import__("json").dumps(resource),
                },
            )
            await session.commit()
    except Exception:
        pass  # audit failures must never break the primary request
