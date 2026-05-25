from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text

from shared.db.session import AsyncSessionLocal

_CACHE_TTL_SECONDS = 60


@dataclass
class RolePermissionGrant:
    role: str
    action_id: str
    grant_type: str  # FULL | CONDITIONAL | READ_ONLY


# Each entry is (grant_or_None, expiry_timestamp)
_cache: dict[tuple[str, str], tuple[Optional[RolePermissionGrant], float]] = {}


async def get_role_permission(
    role: str, action_id: str
) -> Optional[RolePermissionGrant]:
    key = (role, action_id)
    entry = _cache.get(key)
    if entry is not None:
        result, expiry = entry
        if time.monotonic() < expiry:
            return result
        del _cache[key]  # expired

    async with AsyncSessionLocal() as session:
        row = await session.execute(
            text(
                "SELECT grant_type FROM role_permissions "
                "WHERE role_code = :role AND action_id = :action_id AND is_active = true"
            ),
            {"role": role, "action_id": action_id},
        )
        row = row.fetchone()

    result = RolePermissionGrant(role=role, action_id=action_id, grant_type=row[0]) if row else None
    _cache[key] = (result, time.monotonic() + _CACHE_TTL_SECONDS)
    return result


def invalidate_cache() -> None:
    _cache.clear()
