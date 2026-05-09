from __future__ import annotations

import asyncio
from functools import lru_cache

import casbin
import casbin_async_sqlalchemy_adapter as adapter


@lru_cache(maxsize=1)
def get_enforcer(db_url: str) -> casbin.AsyncEnforcer:
    """Returns a shared Casbin enforcer backed by the primary RDS instance."""
    a = adapter.Adapter(db_url)
    enforcer = casbin.AsyncEnforcer("shared/permissions/casbin_model.conf", a)
    return enforcer


async def enforce(role: str, resource: str, action: str, db_url: str) -> bool:
    """Thin wrapper used for explicit Casbin policy checks when needed."""
    e = get_enforcer(db_url)
    return await e.enforce(role, resource, action)
