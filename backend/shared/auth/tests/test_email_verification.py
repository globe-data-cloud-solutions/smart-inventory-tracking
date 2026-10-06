"""Unit tests for shared.auth.email_verification — token issuance and
single-use consumption. DB access is mocked; no real connection required."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from shared.auth.email_verification import (
    _hash_token,
    consume_verification_token,
    issue_verification_token,
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
