import os

import redis.asyncio as redis

_client: redis.Redis | None = None


def get_redis_client() -> redis.Redis:
    """Lazily-created module-level singleton, mirrors shared.db.session's
    engine pattern.

    redis.from_url() does not connect eagerly — the connection pool is only
    used on the first actual command — but REDIS_URL must still be read lazily
    (not at import time) so importing this module never requires the env var
    to be set, e.g. during test collection.
    """
    global _client
    if _client is None:
        _client = redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    return _client
