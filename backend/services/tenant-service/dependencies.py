"""Tenant-service FastAPI dependencies.

Session 2 update: UserContext now carries position-derived claims (role,
warehouse_id, level_number, positions[]) matching the inventory-service.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Optional

from fastapi import Depends, Request
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.rls import set_rls_context
from shared.db.session import AsyncSessionLocal

JWT_SECRET    = os.environ.get("JWT_SECRET", os.environ.get("JWT_SECRET_KEY", ""))
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")

ROLE_AUTHORITY_LEVEL: dict[str, int] = {
    "SA": 1, "TA": 1, "NM": 1,
    "RM": 2,
    "LM": 3,
    "WM": 4,
    "SA_GT": 5, "RT": 5, "AU": 5, "SYS": 5,
}


@dataclass
class UserContext:
    user_id:        str
    role:           str
    tenant_id:      Optional[str]
    warehouse_id:   Optional[str]
    warehouse_name: Optional[str] = None
    position_id:    Optional[str] = None
    position_title: Optional[str] = None
    level_number:   Optional[int] = None
    positions:      list[dict[str, Any]] = field(default_factory=list)
    region_id:      Optional[str] = None

    @property
    def authority_level(self) -> int:
        return ROLE_AUTHORITY_LEVEL.get(self.role, 99)

    @property
    def is_system_account(self) -> bool:
        return self.role in ("SA", "TA") or self.tenant_id is None


def get_current_user(request: Request) -> Optional[UserContext]:
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
    async with AsyncSessionLocal() as session:
        if user is not None:
            await set_rls_context(session, user.tenant_id, user.user_id)
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db_session_for_tenant(
    tenant_id: uuid.UUID,
    user: Optional[UserContext] = Depends(get_current_user),
) -> AsyncGenerator[AsyncSession, None]:
    """RLS set to the URL tenant_id — allows SA to access any tenant's data."""
    async with AsyncSessionLocal() as session:
        if user is not None:
            rls_tenant = str(tenant_id) if user.role == "SA" else user.tenant_id
            await set_rls_context(session, rls_tenant, user.user_id)
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
