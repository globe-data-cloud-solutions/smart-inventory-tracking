"""English email templates — subject/text/html bodies for the two
transactional emails sent outside the app (verification, password reset).
Links are built from APP_BASE_URL read at call time (not import time), so a
test can monkeypatch it without reloading this module.
"""

from __future__ import annotations

import os


def _app_base_url() -> str:
    return os.environ.get("APP_BASE_URL", "http://localhost:3000")


def verification_template(raw_token: str) -> tuple[str, str, str]:
    link = f"{_app_base_url()}/verify-email?token={raw_token}"
    subject = "Verify your email address"
    text_body = (
        "Please verify your email address by visiting the link below:\n\n"
        f"{link}\n\n"
        "If you didn't request this, ignore this email."
    )
    html_body = (
        f"<p>Please verify your email address by clicking the link below:</p>"
        f'<p><a href="{link}">{link}</a></p>'
        f"<p>If you didn't request this, ignore this email.</p>"
    )
    return subject, text_body, html_body


def password_reset_template(raw_token: str) -> tuple[str, str, str]:
    link = f"{_app_base_url()}/reset-password?token={raw_token}"
    subject = "Reset your password"
    text_body = (
        "We received a request to reset your password. Visit the link below "
        "to choose a new one:\n\n"
        f"{link}\n\n"
        "This link expires in 60 minutes.\n\n"
        "If you didn't request this, ignore this email."
    )
    html_body = (
        f"<p>We received a request to reset your password. Click the link "
        f'below to choose a new one:</p><p><a href="{link}">{link}</a></p>'
        f"<p>This link expires in 60 minutes.</p>"
        f"<p>If you didn't request this, ignore this email.</p>"
    )
    return subject, text_body, html_body
