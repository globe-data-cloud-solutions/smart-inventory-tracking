"""Failed-login attempt tracking — shared between auth-service (records and
checks lockouts at login) and tenant-service (clears the lockout immediately
when a TA resets a user's password via personnel_v2.py's update_user())."""
from fastapi import HTTPException

from shared.cache.redis_client import get_redis_client

LOGIN_ATTEMPT_LIMIT   = 5
LOGIN_LOCKOUT_SECONDS = 15 * 60


def _login_attempts_key(email: str) -> str:
    return f"login_attempts:{email.strip().lower()}"


async def _check_login_lockout(email: str) -> None:
    """Raises 429 if this email has hit the failed-attempt threshold."""
    attempts = await get_redis_client().get(_login_attempts_key(email))
    if attempts is not None and int(attempts) >= LOGIN_ATTEMPT_LIMIT:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "TOO_MANY_ATTEMPTS",
                "message": "Too many failed login attempts. Please wait 15 minutes "
                           "before trying again, or contact your administrator to "
                           "reset your account.",
            },
            headers={"Retry-After": str(LOGIN_LOCKOUT_SECONDS)},
        )


async def _record_failed_login(email: str) -> None:
    """INCR the counter and set a 15-minute TTL on the first failure only —
    each subsequent failure within the window extends the count, not the TTL,
    so the lockout window is anchored to the FIRST failed attempt."""
    key = _login_attempts_key(email)
    attempts = await get_redis_client().incr(key)
    if attempts == 1:
        await get_redis_client().expire(key, LOGIN_LOCKOUT_SECONDS)


async def _reset_login_attempts(email: str) -> None:
    await get_redis_client().delete(_login_attempts_key(email))
