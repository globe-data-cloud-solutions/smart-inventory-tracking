"""Unit tests for shared.cache.token_revocation. Redis access is mocked; no
real connection required."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest

from shared.cache.token_revocation import (
    is_token_revoked,
    revoke_tenant_tokens,
    revoke_user_tokens,
)


@pytest.mark.asyncio
async def test_user_revoked_token_issued_before_revoke() -> None:
    client = AsyncMock()
    client.mget = AsyncMock(return_value=[str(int(time.time())), None])

    with patch("shared.cache.token_revocation.get_redis_client", return_value=client):
        revoked = await is_token_revoked(
            {"sub": "user-1", "tenant_id": None, "iat": int(time.time()) - 60}
        )

    assert revoked is True


@pytest.mark.asyncio
async def test_tenant_revoked_token_issued_before_revoke() -> None:
    client = AsyncMock()
    client.mget = AsyncMock(return_value=[None, str(int(time.time()))])

    with patch("shared.cache.token_revocation.get_redis_client", return_value=client):
        revoked = await is_token_revoked(
            {"sub": "user-1", "tenant_id": "tenant-1", "iat": int(time.time()) - 60}
        )

    assert revoked is True


@pytest.mark.asyncio
async def test_token_issued_same_second_as_revoke_not_revoked() -> None:
    now = int(time.time())
    client = AsyncMock()
    client.mget = AsyncMock(return_value=[str(now), None])

    with patch("shared.cache.token_revocation.get_redis_client", return_value=client):
        revoked = await is_token_revoked({"sub": "user-1", "tenant_id": None, "iat": now})

    assert revoked is False  # strict < only


@pytest.mark.asyncio
async def test_no_revocation_keys_returns_false() -> None:
    client = AsyncMock()
    client.mget = AsyncMock(return_value=[None, None])

    with patch("shared.cache.token_revocation.get_redis_client", return_value=client):
        revoked = await is_token_revoked(
            {"sub": "user-1", "tenant_id": "tenant-1", "iat": int(time.time())}
        )

    assert revoked is False


@pytest.mark.asyncio
async def test_is_token_revoked_fails_open_on_redis_error() -> None:
    with patch(
        "shared.cache.token_revocation.get_redis_client",
        side_effect=ConnectionError("down"),
    ):
        revoked = await is_token_revoked(
            {"sub": "user-1", "tenant_id": None, "iat": int(time.time())}
        )

    assert revoked is False


@pytest.mark.asyncio
async def test_missing_iat_is_revoked() -> None:
    client = AsyncMock()
    client.mget = AsyncMock(return_value=[None, None])

    with patch("shared.cache.token_revocation.get_redis_client", return_value=client):
        revoked = await is_token_revoked({"sub": "user-1", "tenant_id": None})

    assert revoked is True


@pytest.mark.asyncio
async def test_revoke_user_tokens_swallows_redis_errors() -> None:
    with patch(
        "shared.cache.token_revocation.get_redis_client",
        side_effect=ConnectionError("down"),
    ):
        await revoke_user_tokens("user-1")  # must not raise


@pytest.mark.asyncio
async def test_revoke_tenant_tokens_swallows_redis_errors() -> None:
    with patch(
        "shared.cache.token_revocation.get_redis_client",
        side_effect=ConnectionError("down"),
    ):
        await revoke_tenant_tokens("tenant-1")  # must not raise


@pytest.mark.asyncio
async def test_revoke_user_tokens_sets_key_with_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", "60")
    client = AsyncMock()
    client.set = AsyncMock()

    with patch("shared.cache.token_revocation.get_redis_client", return_value=client):
        await revoke_user_tokens("User-1")

    client.set.assert_awaited_once()
    args, kwargs = client.set.call_args
    assert args[0] == "revoked_before:user:user-1"
    assert kwargs["ex"] == 60 * 60 + 300


@pytest.mark.asyncio
async def test_revoke_tenant_tokens_sets_key_with_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", "60")
    client = AsyncMock()
    client.set = AsyncMock()

    with patch("shared.cache.token_revocation.get_redis_client", return_value=client):
        await revoke_tenant_tokens("Tenant-1")

    client.set.assert_awaited_once()
    args, kwargs = client.set.call_args
    assert args[0] == "revoked_before:tenant:tenant-1"
    assert kwargs["ex"] == 60 * 60 + 300
