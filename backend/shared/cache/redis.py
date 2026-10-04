"""Redis client management for OTP, sessions, and general caching."""

import os
import redis.asyncio as redis

_redis_client = None


async def get_redis_client():
    """Get or create a Redis async client.
    
    Connects to Redis at REDIS_URL environment variable,
    defaults to localhost:6379.
    """
    global _redis_client
    
    if _redis_client is None:
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        try:
            _redis_client = await redis.from_url(redis_url, decode_responses=False)
            # Test connection
            await _redis_client.ping()
        except Exception as e:
            raise RuntimeError(f"Failed to connect to Redis at {redis_url}: {e}")
    
    return _redis_client


async def close_redis_client():
    """Close the Redis client connection."""
    global _redis_client
    if _redis_client:
        await _redis_client.close()
        _redis_client = None
