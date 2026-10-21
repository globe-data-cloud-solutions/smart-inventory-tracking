"""Unit tests for shared.cache.rate_limit — fixed-window limiter.
Redis access is mocked; no real connection required."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from shared.cache.rate_limit import DEFAULT_LIMITS, client_ip, hit, hit_bucket, limit_for


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


def test_limit_for_returns_default_when_no_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RATE_LIMIT_SIGNUP", raising=False)
    import shared.cache.rate_limit as rl

    rl._limit_cache.clear()
    assert limit_for("signup") == DEFAULT_LIMITS["signup"]


def test_limit_for_valid_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_SIGNUP", "100/3600")
    import shared.cache.rate_limit as rl

    rl._limit_cache.clear()
    assert limit_for("signup") == (100, 3600)


def test_limit_for_invalid_override_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("RATE_LIMIT_SIGNUP", "not-a-valid-value")
    import shared.cache.rate_limit as rl

    rl._limit_cache.clear()
    with caplog.at_level("WARNING"):
        assert limit_for("signup") == DEFAULT_LIMITS["signup"]
    assert "Invalid RATE_LIMIT_SIGNUP" in caplog.text


def test_limit_for_env_name_upper_cases_and_dashes_become_underscores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RATE_LIMIT_STUB_WEBHOOK", "5/10")
    import shared.cache.rate_limit as rl

    rl._limit_cache.clear()
    assert limit_for("stub-webhook") == (5, 10)


@pytest.mark.asyncio
async def test_hit_bucket_uses_configured_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_LOGIN", "1/900")
    import shared.cache.rate_limit as rl

    rl._limit_cache.clear()

    client = AsyncMock()
    client.incr = AsyncMock(side_effect=[1, 2])
    client.expire = AsyncMock()
    client.ttl = AsyncMock(return_value=900)

    with patch("shared.cache.rate_limit.get_redis_client", return_value=client):
        await hit_bucket("login", "1.2.3.4")
        with pytest.raises(HTTPException) as exc_info:
            await hit_bucket("login", "1.2.3.4")

    assert exc_info.value.status_code == 429


def test_client_ip_ignores_x_real_ip_when_trust_proxy_headers_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TRUST_PROXY_HEADERS", raising=False)
    request = MagicMock()
    request.headers = {"X-Real-IP": "9.9.9.9"}
    request.client.host = "127.0.0.1"
    assert client_ip(request) == "127.0.0.1"


def test_client_ip_uses_x_real_ip_when_trust_proxy_headers_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")
    request = MagicMock()
    request.headers = {"X-Real-IP": "9.9.9.9"}
    request.client.host = "127.0.0.1"
    assert client_ip(request) == "9.9.9.9"


def test_client_ip_falls_back_to_request_client_host_when_trusted_but_x_real_ip_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")
    request = MagicMock()
    request.headers = {"X-Real-IP": ""}
    request.client.host = "127.0.0.1"
    assert client_ip(request) == "127.0.0.1"


def test_client_ip_ignores_xff_even_when_trust_proxy_headers_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Downstream services never parse X-Forwarded-For — only the gateway
    does, and it overwrites X-Real-IP with the resolved value. A caller
    sending X-Forwarded-For directly to a downstream service (bypassing the
    gateway) must not be able to spoof its rate-limit bucket through it."""
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")
    request = MagicMock()
    request.headers = {"X-Forwarded-For": "1.1.1.1, 2.2.2.2, 3.3.3.3"}
    request.client.host = "127.0.0.1"
    assert client_ip(request) == "127.0.0.1"


def test_client_ip_falls_back_to_request_client_host() -> None:
    request = MagicMock()
    request.headers = {}
    request.client.host = "127.0.0.1"
    assert client_ip(request) == "127.0.0.1"
