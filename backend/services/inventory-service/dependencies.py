"""Inventory-service FastAPI dependencies.

get_current_user decodes the SMART JWT from the Authorization header.
In unit tests this function is overridden via app.dependency_overrides.
In production the API gateway validates the token before proxying, but
the service decodes it again to extract claims for RBAC / ABAC checks.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from fastapi import Request
from jose import JWTError, jwt

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
