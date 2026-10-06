"""Unit tests for shared.cache.rate_limit — fixed-window limiter.
Redis access is mocked; no real connection required."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from shared.cache.rate_limit import client_ip, hit


@pytest.mark.asyncio
async def test_hit_raises_429_on_limit_plus_one() -> None:
    client = AsyncMock()
    client.incr = AsyncMock(side_effect=[1, 2, 3])
    client.expire = AsyncMock()
    client.ttl = AsyncMock(return_value=55)

    with patch("shared.cache.rate_limit.get_redis_client", return_value=client):
        await hit("test", "1.2.3.4", limit=2, window_seconds=60)
        await hit("test", "1.2.3.4", limit=2, window_seconds=60)
        with pytest.raises(HTTPException) as exc_info:
            await hit("test", "1.2.3.4", limit=2, window_seconds=60)

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail["code"] == "RATE_LIMITED"
    assert exc_info.value.headers["Retry-After"] == "55"


@pytest.mark.asyncio
async def test_hit_fails_open_when_redis_unreachable() -> None:
    with patch("shared.cache.rate_limit.get_redis_client", side_effect=ConnectionError("down")):
        await hit("test", "1.2.3.4", limit=1, window_seconds=60)  # must not raise


def test_client_ip_prefers_x_real_ip_header() -> None:
    request = MagicMock()
    request.headers = {"X-Real-IP": "9.9.9.9"}
    request.client.host = "127.0.0.1"
    assert client_ip(request) == "9.9.9.9"


def test_client_ip_falls_back_to_request_client_host() -> None:
    request = MagicMock()
    request.headers = {}
    request.client.host = "127.0.0.1"
    assert client_ip(request) == "127.0.0.1"
