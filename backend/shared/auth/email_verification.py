"""Email verification tokens — issued post sign-up, consumed via the public
verify-email endpoint. The raw token is returned once by
issue_verification_token() and never stored or logged anywhere except the
dev-mode sender below; only its SHA-256 hash lives in the database.
"""

from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.email.sender import send_email
from shared.email.templates import verification_template

TOKEN_TTL_HOURS = 48


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
    row = (
        await db.execute(
            text(
                "SELECT id, user_id FROM email_verification_tokens "
                "WHERE token_hash = :hash AND used_at IS NULL AND expires_at > now() "
                "FOR UPDATE"
            ),
            {"hash": _hash_token(raw)},
        )
    ).fetchone()
    if row is None:
        return None

    await db.execute(
        text("UPDATE email_verification_tokens SET used_at = now() WHERE id = :id"),
        {"id": str(row.id)},
    )
    # users is RLS-protected and no tenant context exists before sign-in:
    # SECURITY DEFINER auth_mark_email_verified (migration 091, D6).
    await db.execute(
        text("SELECT auth_mark_email_verified(:uid)"),
        {"uid": str(row.user_id)},
    )
    return str(row.user_id)


def send_verification_email(email: str, raw_token: str) -> None:
    """Thin wrapper over shared.email: builds the verification template and
    sends it via the configured delivery mode (log/ses/disabled)."""
    subject, text_body, html_body = verification_template(raw_token)
    app_base_url = os.environ.get("APP_BASE_URL", "http://localhost:3000")
    send_email(
        email,
        subject,
        text_body,
        html_body,
        log_line=f"[DEV EMAIL] verify {email}: {app_base_url}/verify-email?token={raw_token}",
    )


def verification_required() -> bool:
    return os.environ.get("EMAIL_VERIFICATION_REQUIRED", "false").lower() == "true"
