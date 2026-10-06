"""Unit tests for shared.auth.email_verification — token issuance,
single-use consumption, and the ENVIRONMENT-aware delivery-mode default.
DB access is mocked; no real connection required."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from shared.auth.email_verification import (
    _hash_token,
    consume_verification_token,
    issue_verification_token,
    send_verification_email,
)


@pytest.mark.asyncio
async def test_issued_token_hash_never_equals_raw_token() -> None:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())

    raw = await issue_verification_token(db, "user-1")

    assert raw != _hash_token(raw)
    _, params = db.execute.call_args.args
    assert params["hash"] == _hash_token(raw)
    assert params["hash"] != raw


@pytest.mark.asyncio
async def test_consume_token_twice_second_call_returns_none() -> None:
    row = MagicMock(id="tok-1", user_id="user-1")
    select_found = MagicMock()
    select_found.fetchone = MagicMock(return_value=row)
    update_res = MagicMock()

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[select_found, update_res, update_res])

    first = await consume_verification_token(db, "raw-token")
    assert first == "user-1"

    # Second attempt: the SELECT's "used_at IS NULL" filter now excludes the
    # row, so it comes back empty — simulated directly since this is a unit
    # test against the mocked DB, not the real WHERE clause.
    select_not_found = MagicMock()
    select_not_found.fetchone = MagicMock(return_value=None)
    db.execute = AsyncMock(side_effect=[select_not_found])

    second = await consume_verification_token(db, "raw-token")
    assert second is None


@pytest.mark.asyncio
async def test_consume_expired_token_returns_none() -> None:
    # The SELECT's "expires_at > now()" filter excludes an expired token the
    # same way it excludes an already-used one — both come back empty.
    select_not_found = MagicMock()
    select_not_found.fetchone = MagicMock(return_value=None)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=select_not_found)

    result = await consume_verification_token(db, "expired-raw-token")
    assert result is None


@pytest.mark.asyncio
async def test_consume_garbage_token_returns_none() -> None:
    select_not_found = MagicMock()
    select_not_found.fetchone = MagicMock(return_value=None)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=select_not_found)

    result = await consume_verification_token(db, "not-a-real-token")
    assert result is None


def test_send_verification_email_disabled_by_default_off_local(monkeypatch) -> None:
    """An unset ENVIRONMENT (as a misconfigured AWS deploy would have) must
    never fall back to writing the live verification link to CloudWatch."""
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("EMAIL_DELIVERY_MODE", raising=False)
    with pytest.raises(NotImplementedError):
        send_verification_email("user@example.com", "raw-token")


def test_send_verification_email_disabled_when_environment_not_local(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "stage")
    monkeypatch.delenv("EMAIL_DELIVERY_MODE", raising=False)
    with pytest.raises(NotImplementedError):
        send_verification_email("user@example.com", "raw-token")


def test_send_verification_email_logs_when_environment_local(monkeypatch, caplog) -> None:
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.delenv("EMAIL_DELIVERY_MODE", raising=False)
    send_verification_email("user@example.com", "raw-token")
    assert "[DEV EMAIL]" in caplog.text


def test_send_verification_email_explicit_mode_overrides_environment(monkeypatch, caplog) -> None:
    """An explicit EMAIL_DELIVERY_MODE always wins over the ENVIRONMENT-derived default."""
    monkeypatch.setenv("ENVIRONMENT", "stage")
    monkeypatch.setenv("EMAIL_DELIVERY_MODE", "log")
    send_verification_email("user@example.com", "raw-token")
    assert "[DEV EMAIL]" in caplog.text
