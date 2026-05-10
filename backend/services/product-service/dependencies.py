"""Product-service request-scoped dependencies.

Using a named function (not an anonymous lambda) means tests can override it
via app.dependency_overrides[get_current_user] = lambda: fake_user.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException


async def get_current_user() -> Any:
    """Placeholder replaced by the API Gateway JWT middleware in production.
    Returns None here; the auth middleware injects the real user before
    the request reaches this service.
    Overridden in tests via app.dependency_overrides.
    """
    raise HTTPException(status_code=401, detail="Unauthenticated")
