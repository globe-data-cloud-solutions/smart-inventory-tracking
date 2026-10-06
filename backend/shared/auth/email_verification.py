"""Email verification tokens — issued post sign-up, consumed via the public
verify-email endpoint. The raw token is returned once by
issue_verification_token() and never stored or logged anywhere except the
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

TOKEN_TTL_HOURS = 48
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:3000")


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def issue_verification_token(db: AsyncSession, user_id: str) -> str:
    """INSERTs a new hashed token row and returns the raw token (caller's
    responsibility to send it — this function never sends or logs it)."""
    raw = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=TOKEN_TTL_HOURS)
    await db.execute(
        text(
            "INSERT INTO email_verification_tokens (user_id, token_hash, expires_at) "
            "VALUES (:uid, :hash, :expires)"
        ),
        {"uid": str(user_id), "hash": _hash_token(raw), "expires": expires_at},
    )
    return raw


async def consume_verification_token(db: AsyncSession, raw: str) -> Optional[str]:
    """Single-use: locks and marks the matching unused, unexpired token as
    used, and sets the user's email_verified_at. Returns the user_id on
    success, or None if the token is missing, already used, or expired."""
    row = (await db.execute(
        text(
            "SELECT id, user_id FROM email_verification_tokens "
            "WHERE token_hash = :hash AND used_at IS NULL AND expires_at > now() "
            "FOR UPDATE"
        ),
        {"hash": _hash_token(raw)},
    )).fetchone()
    if row is None:
        return None

    await db.execute(
        text("UPDATE email_verification_tokens SET used_at = now() WHERE id = :id"),
        {"id": str(row.id)},
    )
    await db.execute(
        text(
            "UPDATE users SET email_verified_at = now() "
            "WHERE id = :uid AND email_verified_at IS NULL"
        ),
        {"uid": str(row.user_id)},
    )
    return str(row.user_id)


def send_verification_email(email: str, raw_token: str) -> None:
    """EMAIL_DELIVERY_MODE=log (default): logs the verification link — this is
    the dev-mode sender, the only place the raw token is ever written anywhere.
    Any other value: SES is not wired up yet (comes with the AWS deploy)."""
    mode = os.environ.get("EMAIL_DELIVERY_MODE", "log")
    if mode == "log":
        # warning, not info: nothing in this codebase raises the root logger
        # level above the default (WARNING), so info() here would be silently
        # swallowed and this dev-mode line is the only way to retrieve the
        # token locally.
        logger.warning(
            "[DEV EMAIL] verify %s: %s/verify-email?token=%s", email, APP_BASE_URL, raw_token
        )
        return
    raise NotImplementedError("SES delivery not configured")


def verification_required() -> bool:
    return os.environ.get("EMAIL_VERIFICATION_REQUIRED", "false").lower() == "true"
