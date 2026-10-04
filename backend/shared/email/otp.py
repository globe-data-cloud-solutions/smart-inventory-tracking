"""Email verification and OTP management."""

import os
import random
import string
from datetime import datetime, timedelta, timezone
from typing import Optional

from shared.cache.redis import get_redis_client


async def generate_and_send_otp(
    email: str,
    purpose: str = "email_verification",  # email_verification, password_reset, login
) -> str:
    """Generate a 6-digit OTP and store it in Redis.

    Args:
        email: recipient email
        purpose: what the OTP is for

    Returns:
        the 6-digit OTP code

    Raises:
        RuntimeError if Redis is unavailable
    """
    # Generate 6-digit OTP
    otp_code = "".join(random.choices(string.digits, k=6))

    # Store in Redis with 15-minute TTL
    redis = await get_redis_client()
    otp_key = f"otp:{purpose}:{email}"
    ttl_seconds = int(os.environ.get("OTP_EXPIRY_MINUTES", "15")) * 60

    await redis.setex(otp_key, ttl_seconds, otp_code)

    return otp_code


async def verify_otp(
    email: str,
    otp_code: str,
    purpose: str = "email_verification",
) -> bool:
    """Verify an OTP code.

    Args:
        email: email address the OTP was sent to
        otp_code: the code to verify
        purpose: the original purpose

    Returns:
        True if valid and not expired, False otherwise

    Note:
        If valid, the OTP is deleted from Redis to prevent replay attacks.
    """
    redis = await get_redis_client()
    otp_key = f"otp:{purpose}:{email}"

    stored_code = await redis.get(otp_key)
    if not stored_code:
        return False

    # Compare codes
    if stored_code.decode() != otp_code:
        return False

    # Delete OTP to prevent replay
    await redis.delete(otp_key)
    return True


async def get_otp_remaining_time(
    email: str,
    purpose: str = "email_verification",
) -> Optional[int]:
    """Get remaining TTL for an OTP in seconds.

    Args:
        email: email address
        purpose: the purpose

    Returns:
        remaining seconds, or None if OTP doesn't exist or is expired
    """
    redis = await get_redis_client()
    otp_key = f"otp:{purpose}:{email}"

    ttl = await redis.ttl(otp_key)
    if ttl == -2:  # Key doesn't exist
        return None
    if ttl == -1:  # Key exists but no TTL
        return None
    return ttl


async def resend_otp(email: str, purpose: str = "email_verification") -> str:
    """Resend OTP to an email (generates new code, resets TTL).

    Args:
        email: recipient email
        purpose: the purpose

    Returns:
        the new 6-digit OTP code
    """
    redis = await get_redis_client()
    otp_key = f"otp:{purpose}:{email}"

    # Delete old OTP
    await redis.delete(otp_key)

    # Generate and store new OTP
    return await generate_and_send_otp(email, purpose)


async def clear_otp(
    email: str,
    purpose: str = "email_verification",
) -> None:
    """Clear an OTP (e.g., after successful signup).

    Args:
        email: email address
        purpose: the purpose
    """
    redis = await get_redis_client()
    otp_key = f"otp:{purpose}:{email}"
    await redis.delete(otp_key)
