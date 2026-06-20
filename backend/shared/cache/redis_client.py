import os

import redis.asyncio as redis

_client = redis.from_url(
    os.environ["REDIS_URL"],
    decode_responses=True,
)


def get_redis_client() -> redis.Redis:
    """Module-level singleton, mirrors shared.db.session's engine pattern.

    redis.from_url() does not connect eagerly — the connection pool is only
    used on the first actual command, so importing this module is cheap.
    """
    return _client
