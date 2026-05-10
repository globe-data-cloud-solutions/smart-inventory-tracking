"""Tenant scoping utility — mirrors reference effective_tenant_id() pattern.

SA role can see all tenants (override=None means all, override=UUID means specific).
All other roles are restricted to their own tenant_id.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional


def effective_tenant_id(
    user: Any,
    override: Optional[uuid.UUID] = None,
) -> Optional[uuid.UUID]:
    """Return the tenant UUID to filter by, or None (= all tenants) for SA.

    Args:
        user:     The current user context object (must have .role and .tenant_id).
        override: A specific tenant UUID passed by the caller (only honoured for SA).

    Returns:
        None      — SA with no override: query spans all tenants (use with care on read replicas).
        UUID      — SA with override, or any non-SA user: restrict to this tenant.
    """
    if getattr(user, "role", None) == "SA":
        return override  # None = all tenants, UUID = specific one
    tid = getattr(user, "tenant_id", None)
    return uuid.UUID(str(tid)) if tid else None
