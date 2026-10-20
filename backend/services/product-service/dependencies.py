"""Product-service FastAPI dependencies.

get_current_user decodes the SMART JWT from the Authorization header.
get_db_session opens an SQLAlchemy session and sets the PostgreSQL RLS context
from the authenticated user's tenant_id so tenant-scoped tables are filtered.

In unit tests these functions are overridden via app.dependency_overrides.
In production the API gateway validates the token before proxying, but
the service decodes it again to extract claims for RBAC / ABAC checks.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import AsyncGenerator, Optional

from fastapi import Depends, Request
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.rls import set_rls_context
from shared.db.session import AsyncSessionLocal

JWT_SECRET = os.environ.get("JWT_SECRET") or os.environ.get("JWT_SECRET_KEY")
if not JWT_SECRET:
    raise RuntimeError(
        "JWT_SECRET (or JWT_SECRET_KEY) must be set — refusing to start with an "
        "empty signing secret."
    )
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")


@dataclass
class UserContext:
    user_id: str
    role: str
    tenant_id: str
    warehouse_id: Optional[str]
    region_id: Optional[str]


def get_current_user(request: Request) -> Optional[UserContext]:
    """Decode SMART JWT from Authorization header. Returns None for missing/invalid tokens.

    The @require_permission decorator then raises 401 when user is None.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth.removeprefix("Bearer ")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return UserContext(
            user_id=str(payload.get("sub", "")),
            role=str(payload.get("role", "")),
            tenant_id=str(payload.get("tenant_id", "")),
            warehouse_id=payload.get("warehouse_id"),
            region_id=payload.get("region_id"),
        )
    except JWTError:
        return None


async def get_db_session(
    user: Optional[UserContext] = Depends(get_current_user),
) -> AsyncGenerator[AsyncSession, None]:
    """Primary DB session with RLS context set from the authenticated user's tenant_id."""
    async with AsyncSessionLocal() as session:
        if user is not None:
            # SA has no tenant: its tenant_id here is str(None), so bind none and
            # rely on the SA flag instead of casting "None" to uuid.
            is_sa = user.role == "SA"
            await set_rls_context(
                session, "" if is_sa else user.tenant_id, user.user_id, is_sa=is_sa
            )
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
