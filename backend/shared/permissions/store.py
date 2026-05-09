from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text

from shared.db.session import AsyncSessionLocal


@dataclass
class RolePermissionGrant:
    role: str
    action_id: str
    grant_type: str  # FULL | CONDITIONAL | READ_ONLY


_cache: dict[tuple[str, str], Optional[RolePermissionGrant]] = {}


async def get_role_permission(
    role: str, action_id: str
) -> Optional[RolePermissionGrant]:
    key = (role, action_id)
    if key in _cache:
        return _cache[key]

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
    _cache[key] = result
    return result


def invalidate_cache() -> None:
    _cache.clear()
