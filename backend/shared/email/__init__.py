from __future__ import annotations

from shared.email.sender import get_delivery_mode, send_email
from shared.email.templates import password_reset_template, verification_template

__all__ = [
    "get_delivery_mode",
    "send_email",
    "password_reset_template",
    "verification_template",
]
