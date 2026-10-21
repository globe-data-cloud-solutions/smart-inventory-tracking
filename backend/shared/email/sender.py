"""Pluggable email sender — "log" (dev-mode, writes to the logger), "ses"
(AWS SES), or "disabled" (no-op). Mode defaults to "log" only when
ENVIRONMENT=local, matching the rule the two auth call sites used before
this module existed; everything else (an unset ENVIRONMENT included, as on
a misconfigured AWS deploy) defaults to "disabled" so a live link never
ends up in CloudWatch.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def get_delivery_mode() -> str:
    default_mode = "log" if os.environ.get("ENVIRONMENT", "") == "local" else "disabled"
    return os.environ.get("EMAIL_DELIVERY_MODE", default_mode)


def _ses_client():
    import boto3

    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    return boto3.client("sesv2", region_name=region)


def send_email(to: str, subject: str, text_body: str, html_body: str, *, log_line: str) -> None:
    mode = get_delivery_mode()

    if mode == "log":
        # warning, not info: nothing in this codebase raises the root logger
        # level above the default (WARNING), so info() here would be
        # silently swallowed and this dev-mode line is the only way to
        # retrieve a token locally.
        logger.warning(log_line)
        return

    if mode == "ses":
        from_email = os.environ.get("EMAIL_FROM")
        if not from_email:
            logger.error("EMAIL_FROM is not set — cannot send email via SES to %s", to)
            return
        client = _ses_client()
        client.send_email(
            FromEmailAddress=from_email,
            Destination={"ToAddresses": [to]},
            Content={
                "Simple": {
                    "Subject": {"Data": subject},
                    "Body": {
                        "Text": {"Data": text_body},
                        "Html": {"Data": html_body},
                    },
                }
            },
        )
        return

    logger.error("email delivery disabled (EMAIL_DELIVERY_MODE=%s) — not sending to %s", mode, to)
