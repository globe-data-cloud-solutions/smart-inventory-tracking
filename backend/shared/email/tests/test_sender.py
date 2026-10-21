"""Unit tests for shared.email.sender — delivery-mode selection and the
three send paths (log/ses/disabled). No network; the SES client is replaced
via the module-level factory function."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from shared.email.sender import get_delivery_mode, send_email


def test_default_mode_is_log_only_when_environment_local(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.delenv("EMAIL_DELIVERY_MODE", raising=False)
    assert get_delivery_mode() == "log"


def test_default_mode_is_disabled_when_environment_not_local(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "stage")
    monkeypatch.delenv("EMAIL_DELIVERY_MODE", raising=False)
    assert get_delivery_mode() == "disabled"


def test_default_mode_is_disabled_when_environment_unset(monkeypatch) -> None:
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("EMAIL_DELIVERY_MODE", raising=False)
    assert get_delivery_mode() == "disabled"


def test_log_mode_emits_exact_dev_email_line(monkeypatch, caplog) -> None:
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.delenv("EMAIL_DELIVERY_MODE", raising=False)
    send_email(
        "user@example.com",
        "subject",
        "text body contains https://x/y?token=raw-token",
        "html body",
        log_line="[DEV EMAIL] verify user@example.com: http://localhost:3000/verify-email?token=raw-token",
    )
    assert (
        caplog.text.count(
            "[DEV EMAIL] verify user@example.com: http://localhost:3000/verify-email?token=raw-token"
        )
        == 1
    )
    # The token never appears anywhere except inside the one expected line.
    assert "raw-token" not in caplog.text.replace(
        "[DEV EMAIL] verify user@example.com: http://localhost:3000/verify-email?token=raw-token",
        "",
    )


def test_ses_mode_calls_send_email_with_expected_args(monkeypatch) -> None:
    monkeypatch.setenv("EMAIL_DELIVERY_MODE", "ses")
    monkeypatch.setenv("EMAIL_FROM", "no-reply@example.com")
    fake_client = MagicMock()

    with patch("shared.email.sender._ses_client", return_value=fake_client):
        send_email(
            "user@example.com",
            "Reset your password",
            "text body with https://app/reset-password?token=raw-token",
            "<p>html body with https://app/reset-password?token=raw-token</p>",
            log_line="[DEV EMAIL] reset user@example.com: should-not-be-used",
        )

    fake_client.send_email.assert_called_once()
    _, kwargs = fake_client.send_email.call_args
    assert kwargs["FromEmailAddress"] == "no-reply@example.com"
    assert kwargs["Destination"] == {"ToAddresses": ["user@example.com"]}
    assert kwargs["Content"]["Simple"]["Subject"]["Data"] == "Reset your password"
    assert "token=raw-token" in kwargs["Content"]["Simple"]["Body"]["Text"]["Data"]


def test_ses_mode_without_email_from_does_not_send(monkeypatch, caplog) -> None:
    monkeypatch.setenv("EMAIL_DELIVERY_MODE", "ses")
    monkeypatch.delenv("EMAIL_FROM", raising=False)
    fake_client = MagicMock()

    with patch("shared.email.sender._ses_client", return_value=fake_client):
        send_email(
            "user@example.com",
            "subject",
            "text",
            "html",
            log_line="[DEV EMAIL] should-not-be-used",
        )

    fake_client.send_email.assert_not_called()
    assert "EMAIL_FROM" in caplog.text


def test_ses_client_error_propagates_to_caller(monkeypatch) -> None:
    monkeypatch.setenv("EMAIL_DELIVERY_MODE", "ses")
    monkeypatch.setenv("EMAIL_FROM", "no-reply@example.com")
    fake_client = MagicMock()
    fake_client.send_email.side_effect = RuntimeError("SES is down")

    with patch("shared.email.sender._ses_client", return_value=fake_client):
        with pytest.raises(RuntimeError, match="SES is down"):
            send_email("user@example.com", "subject", "text", "html", log_line="unused")


def test_disabled_mode_does_not_send_and_logs_error(monkeypatch, caplog) -> None:
    monkeypatch.setenv("EMAIL_DELIVERY_MODE", "disabled")
    send_email("user@example.com", "subject", "text", "html", log_line="[DEV EMAIL] unused")
    assert "disabled" in caplog.text.lower()


def test_unknown_mode_treated_as_disabled(monkeypatch, caplog) -> None:
    monkeypatch.setenv("EMAIL_DELIVERY_MODE", "something-else")
    send_email("user@example.com", "subject", "text", "html", log_line="[DEV EMAIL] unused")
    assert "disabled" in caplog.text.lower() or "something-else" in caplog.text
