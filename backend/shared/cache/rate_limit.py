"""Redis fixed-window rate limiter for public endpoints (sign-up, email
verification). Fails OPEN if Redis is unreachable — sign-up must not depend
on Redis being up in local dev; a warning is logged whenever that happens.
"""
from __future__ import annotations

import logging

from fastapi import HTTPException, Request

from shared.cache.redis_client import get_redis_client

logger = logging.getLogger(__name__)


async def hit(bucket: str, key: str, limit: int, window_seconds: int) -> None:
    """INCR the fixed window counter for bucket+key; raise 429 once `limit`
    is exceeded within `window_seconds` of the first hit."""
    redis_key = f"rl:{bucket}:{key}"
    try:
        client = get_redis_client()
        count = await client.incr(redis_key)
        if count == 1:
            await client.expire(redis_key, window_seconds)
        if count > limit:
            ttl = await client.ttl(redis_key)
            retry_after = ttl if ttl and ttl > 0 else window_seconds
            raise HTTPException(
                status_code=429,
                detail={"code": "RATE_LIMITED", "message": "Too many requests. Please try again later."},
                headers={"Retry-After": str(retry_after)},
            )
    except HTTPException:
        raise
    except Exception as exc:
        # Fail-open: a Redis outage must never block sign-up/verification.
        logger.warning("Rate limiter unavailable (fail-open) bucket=%s key=%s: %s", bucket, key, exc)


def client_ip(request: Request) -> str:
    header_ip = request.headers.get("X-Real-IP")
    if header_ip:
        return header_ip
    return request.client.host if request.client else "unknown"
