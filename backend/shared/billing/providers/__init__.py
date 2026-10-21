"""Payment provider registry — no network calls here.

A PaymentProvider turns a PENDING payment into something the frontend can
redirect to (checkout()) and verifies an inbound webhook (parse_webhook()).

Two providers exist today:
  MANUAL — the SA marks a payment paid by hand (bank transfer, cash, etc.).
           checkout() returns instructions; there is no webhook to receive.
  STUB   — a fake gateway for local testing of the webhook path: an
           HMAC-signed JSON callback over STUB_WEBHOOK_SECRET.

This is the slot a real gateway (e.g. Chapa, Telebirr) plugs into later —
just implement PaymentProvider and add it to _PROVIDERS. Nothing more.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class WebhookEvent:
    event: str  # "payment.succeeded" | "payment.failed"
    payment_id: str
    provider_reference: str | None


class PaymentProvider(Protocol):
    name: str

    def checkout(self, payment: dict[str, Any]) -> dict[str, Any]:
        """What the frontend would redirect to (or show) to pay this payment."""
        ...

    def parse_webhook(self, headers: Mapping[str, str], body: bytes) -> WebhookEvent:
        """Verify and parse an inbound webhook. Raises ValueError on anything
        invalid (bad signature, malformed payload) — never returns a partial
        or best-guess event."""
        ...


class ManualProvider:
    name = "MANUAL"

    def checkout(self, payment: dict[str, Any]) -> dict[str, Any]:
        return {"type": "MANUAL", "instructions_key": "billing.manual_instructions"}

    def parse_webhook(self, headers: Mapping[str, str], body: bytes) -> WebhookEvent:
        # Manual payments are marked paid by the SA, not by a webhook.
        raise NotImplementedError("MANUAL provider has no webhook")


class StubProvider:
    name = "STUB"

    def checkout(self, payment: dict[str, Any]) -> dict[str, Any]:
        base_url = os.environ.get("APP_BASE_URL", "http://localhost:3000")
        return {
            "type": "REDIRECT",
            "url": f"{base_url}/billing/stub-checkout?payment={payment['payment_id']}",
        }

    def parse_webhook(self, headers: Mapping[str, str], body: bytes) -> WebhookEvent:
        secret = os.environ.get("STUB_WEBHOOK_SECRET")
        if not secret:
            # Missing secret means we can verify nothing — reject everything,
            # never fall back to trusting an unsigned payload.
            raise ValueError("INVALID_SIGNATURE")

        signature = headers.get("X-Stub-Signature", "")
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not signature or not hmac.compare_digest(signature, expected):
            raise ValueError("INVALID_SIGNATURE")

        try:
            data = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("INVALID_PAYLOAD") from exc

        try:
            event = data["event"]
            payment_id = data["payment_id"]
        except (KeyError, TypeError) as exc:
            raise ValueError("INVALID_PAYLOAD") from exc
        if event not in ("payment.succeeded", "payment.failed"):
            raise ValueError("INVALID_PAYLOAD")

        return WebhookEvent(
            event=event,
            payment_id=str(payment_id),
            provider_reference=data.get("provider_reference"),
        )


_PROVIDERS: dict[str, PaymentProvider] = {
    "MANUAL": ManualProvider(),
    "STUB": StubProvider(),
}


def get_provider(name: str) -> PaymentProvider:
    provider = _PROVIDERS.get(name)
    if provider is None:
        raise ValueError(f"Unknown payment provider: {name}")
    return provider
