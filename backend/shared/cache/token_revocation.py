"""Token revocation via Redis "revoked-before" timestamps.

Revoking a user or tenant writes the current epoch second to
"revoked_before:user:{user_id}" / "revoked_before:tenant:{tenant_id}". A JWT
is revoked if its `iat` predates that stored value — so every token issued
before the revoke (user tokens for revoke_user_tokens, every token belonging
to the tenant for revoke_tenant_tokens) stops working, while tokens issued
after the revoke keep working.

Mirrors shared.cache.rate_limit's fail-open pattern: a Redis outage must
never block the business operation that triggered a revoke (password change,
deactivation, suspend) and must never incorrectly lock a caller out either —
so revocation checks fail OPEN (not revoked) on any Redis error, while the
revoke write itself swallows errors and never raises.
"""

from __future__ import annotations

import logging
import os
import time

from shared.cache.redis_client import get_redis_client

logger = logging.getLogger(__name__)


def _ttl_seconds() -> int:
    return int(os.environ.get("JWT_EXPIRE_MINUTES", "60")) * 60 + 300


async def revoke_user_tokens(user_id: str) -> None:
    key = f"revoked_before:user:{str(user_id).lower()}"
    try:
        client = get_redis_client()
        await client.set(key, int(time.time()), ex=_ttl_seconds())
    except Exception as exc:
        logger.error("Failed to revoke tokens for user=%s: %s", user_id, exc)


async def revoke_tenant_tokens(tenant_id: str) -> None:
    key = f"revoked_before:tenant:{str(tenant_id).lower()}"
    try:
        client = get_redis_client()
        await client.set(key, int(time.time()), ex=_ttl_seconds())
    except Exception as exc:
        logger.error("Failed to revoke tokens for tenant=%s: %s", tenant_id, exc)


async def is_token_revoked(payload: dict) -> bool:
    iat = payload.get("iat")
    if not isinstance(iat, int):
        return True

    user_id = payload.get("sub")
    tenant_id = payload.get("tenant_id")

    keys = [f"revoked_before:user:{str(user_id).lower()}"]
    if tenant_id is not None:
        keys.append(f"revoked_before:tenant:{str(tenant_id).lower()}")

    try:
        client = get_redis_client()
        values = await client.mget(keys)
    except Exception as exc:
        logger.warning("Token revocation check unavailable (fail-open): %s", exc)
        return False

    for raw in values:
        if raw is None:
            continue
        try:
            revoked_before = int(raw)
        except (TypeError, ValueError):
            continue
        if iat < revoked_before:
            return True
    return False
