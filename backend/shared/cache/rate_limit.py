"""Redis fixed-window rate limiter for public endpoints (sign-up, email
verification, login). Fails OPEN if Redis is unreachable — sign-up must not
depend on Redis being up in local dev; a warning is logged whenever that
happens.

Per-bucket limits are the production defaults below, overridable per bucket
via RATE_LIMIT_<BUCKET>=<limit>/<window_s> (bucket name upper-cased, '-' →
'_') for local-only tuning — e.g. RATE_LIMIT_SIGNUP=100/3600. An invalid
override value is logged and ignored (falls back to the default); it never
crashes the service.
"""
from __future__ import annotations

import logging
import os

from fastapi import HTTPException, Request

from shared.cache.redis_client import get_redis_client

logger = logging.getLogger(__name__)

# bucket -> (limit, window_seconds) — production defaults.
DEFAULT_LIMITS: dict[str, tuple[int, int]] = {
    "packages": (60, 60),
    "signup": (5, 3600),
    "verify": (20, 3600),
    "resend": (3, 3600),
    "forgot": (3, 3600),
    "reset": (10, 3600),
    "stub-webhook": (120, 60),
    "login": (20, 900),
}

_limit_cache: dict[str, tuple[int, int]] = {}


def limit_for(bucket: str) -> tuple[int, int]:
    """Resolve (limit, window_seconds) for `bucket`: env override if present
    and valid, else the production default. Cached per process — env vars
    don't change at runtime."""
    if bucket in _limit_cache:
        return _limit_cache[bucket]

    default = DEFAULT_LIMITS[bucket]
    env_name = f"RATE_LIMIT_{bucket.upper().replace('-', '_')}"
    raw = os.environ.get(env_name)
    resolved = default
    if raw:
        try:
            limit_str, window_str = raw.split("/", 1)
            resolved = (int(limit_str), int(window_str))
        except (ValueError, TypeError):
            logger.warning(
                "Invalid %s=%r — expected <limit>/<window_s>; using default %s",
                env_name, raw, default,
            )
            resolved = default

    _limit_cache[bucket] = resolved
    return resolved


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


async def hit_bucket(bucket: str, key: str) -> None:
    """hit() using the configured (env-overridable) limit/window for `bucket`."""
    limit, window_seconds = limit_for(bucket)
    await hit(bucket, key, limit=limit, window_seconds=window_seconds)


def client_ip(request: Request) -> str:
    """Caller IP for rate-limiting. Proxy headers (X-Forwarded-For) are only
    trusted when TRUST_PROXY_HEADERS=true (set on ECS behind the ALB) — in
    that case the LAST entry of X-Forwarded-For is used, since that's the one
    the ALB itself appended. X-Real-IP is never read: it is not set by the
    ALB and trusting it from an untrusted client would let callers spoof
    their rate-limit bucket."""
    if os.environ.get("TRUST_PROXY_HEADERS", "").lower() == "true":
        xff = request.headers.get("X-Forwarded-For")
        if xff:
            last = xff.split(",")[-1].strip()
            if last:
                return last
    return request.client.host if request.client else "unknown"
