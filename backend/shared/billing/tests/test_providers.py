"""Unit tests for shared.billing.providers — MANUAL/STUB checkout shapes and
StubProvider's HMAC-signed webhook verification. No DB, no network."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from shared.billing.providers import ManualProvider, StubProvider, get_provider


def test_get_provider_returns_registered_providers() -> None:
    assert isinstance(get_provider("MANUAL"), ManualProvider)
    assert isinstance(get_provider("STUB"), StubProvider)


def test_get_provider_unknown_raises() -> None:
    with pytest.raises(ValueError):
        get_provider("CHAPA")


def test_manual_checkout_returns_instructions() -> None:
    out = ManualProvider().checkout({"payment_id": "payment-1"})
    assert out == {"type": "MANUAL", "instructions_key": "billing.manual_instructions"}


def test_manual_parse_webhook_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        ManualProvider().parse_webhook({}, b"{}")


def test_stub_checkout_returns_redirect_url(monkeypatch) -> None:
    monkeypatch.setenv("APP_BASE_URL", "https://app.example.com")
    out = StubProvider().checkout({"payment_id": "payment-1"})
    assert out == {
        "type": "REDIRECT",
        "url": "https://app.example.com/billing/stub-checkout?payment=payment-1",
    }


def _signed_body(secret: str, payload: dict) -> tuple[bytes, str]:
    body = json.dumps(payload).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, signature


def test_stub_parse_webhook_good_signature_succeeded(monkeypatch) -> None:
    monkeypatch.setenv("STUB_WEBHOOK_SECRET", "s5-local-secret")
    body, sig = _signed_body(
        "s5-local-secret",
        {
            "event": "payment.succeeded",
            "payment_id": "payment-1",
            "provider_reference": "STUB-REF-1",
        },
    )

    event = StubProvider().parse_webhook({"X-Stub-Signature": sig}, body)

    assert event.event == "payment.succeeded"
    assert event.payment_id == "payment-1"
    assert event.provider_reference == "STUB-REF-1"


def test_stub_parse_webhook_good_signature_failed(monkeypatch) -> None:
    monkeypatch.setenv("STUB_WEBHOOK_SECRET", "s5-local-secret")
    body, sig = _signed_body(
        "s5-local-secret",
        {
            "event": "payment.failed",
            "payment_id": "payment-1",
            "provider_reference": None,
        },
    )

    event = StubProvider().parse_webhook({"X-Stub-Signature": sig}, body)
    assert event.event == "payment.failed"


def test_stub_parse_webhook_bad_signature_raises(monkeypatch) -> None:
    monkeypatch.setenv("STUB_WEBHOOK_SECRET", "s5-local-secret")
    body, _ = _signed_body(
        "s5-local-secret", {"event": "payment.succeeded", "payment_id": "payment-1"}
    )

    with pytest.raises(ValueError, match="INVALID_SIGNATURE"):
        StubProvider().parse_webhook({"X-Stub-Signature": "0" * 64}, body)


def test_stub_parse_webhook_missing_signature_header_raises(monkeypatch) -> None:
    monkeypatch.setenv("STUB_WEBHOOK_SECRET", "s5-local-secret")
    body, _ = _signed_body(
        "s5-local-secret", {"event": "payment.succeeded", "payment_id": "payment-1"}
    )

    with pytest.raises(ValueError, match="INVALID_SIGNATURE"):
        StubProvider().parse_webhook({}, body)


def test_stub_parse_webhook_missing_secret_rejects_everything(monkeypatch) -> None:
    monkeypatch.delenv("STUB_WEBHOOK_SECRET", raising=False)
    body, sig = _signed_body("whatever", {"event": "payment.succeeded", "payment_id": "payment-1"})

    with pytest.raises(ValueError, match="INVALID_SIGNATURE"):
        StubProvider().parse_webhook({"X-Stub-Signature": sig}, body)


def test_stub_parse_webhook_malformed_payload_raises(monkeypatch) -> None:
    monkeypatch.setenv("STUB_WEBHOOK_SECRET", "s5-local-secret")
    body = b"not json"
    sig = hmac.new(b"s5-local-secret", body, hashlib.sha256).hexdigest()

    with pytest.raises(ValueError, match="INVALID_PAYLOAD"):
        StubProvider().parse_webhook({"X-Stub-Signature": sig}, body)


def test_stub_parse_webhook_unknown_event_raises(monkeypatch) -> None:
    monkeypatch.setenv("STUB_WEBHOOK_SECRET", "s5-local-secret")
    body, sig = _signed_body(
        "s5-local-secret", {"event": "payment.refunded", "payment_id": "payment-1"}
    )

    with pytest.raises(ValueError, match="INVALID_PAYLOAD"):
        StubProvider().parse_webhook({"X-Stub-Signature": sig}, body)
