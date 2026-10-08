"""Password reset tokens — issued via the public forgot-password endpoint,
consumed via the public reset-password endpoint. The raw token is returned
once by issue_reset_token() and never stored or logged anywhere except the
dev-mode sender below; only its SHA-256 hash lives in the database.
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

TOKEN_TTL_MINUTES = 60
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:3000")


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def issue_reset_token(db: AsyncSession, user_id: str) -> str:
    """Invalidates the user's earlier unused reset tokens, INSERTs a new
    hashed token row, and returns the raw token (caller's responsibility to
    send it — this function never sends or logs it)."""
    await db.execute(
        text(
            "UPDATE password_reset_tokens SET used_at = now() "
            "WHERE user_id = :uid AND used_at IS NULL"
        ),
        {"uid": str(user_id)},
    )
    raw = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_TTL_MINUTES)
    await db.execute(
        text(
            "INSERT INTO password_reset_tokens (user_id, token_hash, expires_at) "
            "VALUES (:uid, :hash, :expires)"
        ),
        {"uid": str(user_id), "hash": _hash_token(raw), "expires": expires_at},
    )
    return raw


async def consume_reset_token(db: AsyncSession, raw: str) -> Optional[str]:
    """Single-use: locks and marks the matching unused, unexpired token as
    used. Returns the user_id on success, or None if the token is missing,
    already used, or expired."""
    row = (await db.execute(
        text(
            "SELECT id, user_id FROM password_reset_tokens "
            "WHERE token_hash = :hash AND used_at IS NULL AND expires_at > now() "
            "FOR UPDATE"
        ),
        {"hash": _hash_token(raw)},
    )).fetchone()
    if row is None:
        return None

    await db.execute(
        text("UPDATE password_reset_tokens SET used_at = now() WHERE id = :id"),
        {"id": str(row.id)},
    )
    return str(row.user_id)


def send_reset_email(email: str, raw_token: str) -> None:
    """EMAIL_DELIVERY_MODE default depends on ENVIRONMENT: "log" (the dev-mode
    sender, the only place the raw token is ever written anywhere) only when
    ENVIRONMENT=local; everything else (including an unset ENVIRONMENT, as on
    AWS) defaults to "disabled" so a misconfigured deploy never writes a live
    reset link to CloudWatch. "disabled" or any other value: SES is not wired
    up yet (comes with the AWS deploy)."""
    default_mode = "log" if os.environ.get("ENVIRONMENT", "") == "local" else "disabled"
    mode = os.environ.get("EMAIL_DELIVERY_MODE", default_mode)
    if mode == "log":
        logger.warning(
            "[DEV EMAIL] reset %s: %s/reset-password?token=%s", email, APP_BASE_URL, raw_token
        )
        return
    raise NotImplementedError("SES delivery not configured")
