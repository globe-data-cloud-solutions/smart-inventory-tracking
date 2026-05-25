"""Inventory-service FastAPI dependencies.

get_current_user decodes the SMART JWT from the Authorization header.
get_db_session / get_read_db_session open an SQLAlchemy session and set the
PostgreSQL RLS context from the authenticated user's tenant_id so that all
tenant-scoped queries are properly filtered.

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
from shared.db.session import AsyncReadSessionLocal, AsyncSessionLocal

JWT_SECRET    = os.environ.get("JWT_SECRET", os.environ.get("JWT_SECRET_KEY", ""))
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
    """Primary DB session with RLS context set from the authenticated user's tenant_id.

    @require_permission raises 401 before the handler executes for unauthenticated
    requests, so user is None only in tests that override this dependency explicitly.
    """
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
    """Read-replica session for analytics/reports — RLS context still required."""
    async with AsyncReadSessionLocal() as session:
        if user is not None:
            await set_rls_context(session, user.tenant_id, user.user_id)
        yield session
