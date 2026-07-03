"""Inventory-service FastAPI dependencies.

Session 2: UserContext now carries position-derived claims.
  - role, warehouse_id, level_number come from the user's PRIMARY active
    position (resolved at login time by auth-service and embedded in JWT).
  - positions[] lists ALL active assignments for multi-facility ABAC checks.
  - authority_level property mirrors the backend ROLE_AUTHORITY_LEVEL scale.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Optional

from fastapi import Depends, Request
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.rls import set_rls_context
from shared.db.session import AsyncReadSessionLocal, AsyncSessionLocal

JWT_SECRET = os.environ.get("JWT_SECRET") or os.environ.get("JWT_SECRET_KEY")
if not JWT_SECRET:
    raise RuntimeError(
        "JWT_SECRET (or JWT_SECRET_KEY) must be set — refusing to start with an "
        "empty signing secret."
    )
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")

# Authority tier (lower = higher authority).  Mirrors approval_service.py.
# Defined here so UserContext.authority_level is self-contained.
ROLE_AUTHORITY_LEVEL: dict[str, int] = {
    "SA":    1,
    "TA":    1,
    "NM":    1,
    "RM":    2,
    "LM":    3,
    "WM":    4,
    "SA_GT": 5,
    "RT":    5,
    "AU":    5,
    "SYS":   5,
}


@dataclass
class UserContext:
    """Authenticated user parsed from a SMART JWT.

    Primary-position fields (role, warehouse_id, level_number) reflect the
    user's main facility assignment.  positions[] lists ALL active assignments
    so ABAC checks can evaluate multi-facility authority.
    """
    user_id:        str
    role:           str
    tenant_id:      Optional[str]
    warehouse_id:   Optional[str]
    # New position-derived fields (Session 2)
    warehouse_name: Optional[str] = None
    position_id:    Optional[str] = None
    position_title: Optional[str] = None
    level_number:   Optional[int] = None
    positions:      list[dict[str, Any]] = field(default_factory=list)
    # Legacy / backward-compat
    region_id:      Optional[str] = None

    # ── Computed properties ──────────────────────────────────────────────────

    @property
    def authority_level(self) -> int:
        """Numeric authority level (lower = higher authority)."""
        return ROLE_AUTHORITY_LEVEL.get(self.role, 99)

    @property
    def is_system_account(self) -> bool:
        """True for SA/TA users and platform accounts with no tenant."""
        return self.role in ("SA", "TA") or self.tenant_id is None

    def has_authority_over(self, node_id: str) -> bool:
        """True if any active position gives this user authority over node_id.

        Checks all positions (PRIMARY + ACTING + DELEGATE) — expired assignments
        are excluded by the JWT (auth-service only includes currently-active ones).
        """
        return any(
            str(p.get("node_id", "")) == str(node_id)
            for p in self.positions
        )


def get_current_user(request: Request) -> Optional[UserContext]:
    """Decode SMART JWT from Authorization header.

    Returns None for missing/invalid tokens.  The @require_permission decorator
    raises 401 when user is None.

    Handles both old JWTs (no position fields) and new position-aware JWTs from
    Session 2 auth-service — missing fields default to None gracefully.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth.removeprefix("Bearer ")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return UserContext(
            user_id=        str(payload.get("sub", "")),
            role=           str(payload.get("role", "")),
            tenant_id=      payload.get("tenant_id"),
            warehouse_id=   payload.get("warehouse_id"),
            warehouse_name= payload.get("warehouse_name"),
            position_id=    payload.get("position_id"),
            position_title= payload.get("position_title"),
            level_number=   payload.get("level_number"),
            positions=      list(payload.get("positions", [])),
            region_id=      payload.get("region_id"),
        )
    except JWTError:
        return None


async def get_db_session(
    user: Optional[UserContext] = Depends(get_current_user),
) -> AsyncGenerator[AsyncSession, None]:
    """Primary DB session with RLS context from authenticated user's tenant_id."""
    async with AsyncSessionLocal() as session:
        if user is not None:
            await set_rls_context(session, user.tenant_id, user.user_id)
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_read_db_session(
    user: Optional[UserContext] = Depends(get_current_user),
) -> AsyncGenerator[AsyncSession, None]:
    """Read-replica session for analytics/reports."""
    async with AsyncReadSessionLocal() as session:
        if user is not None:
            await set_rls_context(session, user.tenant_id, user.user_id)
        yield session
