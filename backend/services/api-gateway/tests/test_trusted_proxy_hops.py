"""Tests for api-gateway's TRUSTED_PROXY_HOPS — the X-Real-IP sent downstream
must come from the real caller, not the ALB, once the gateway sits behind one.
TRUSTED_PROXY_HOPS is read at module import time, so each test reloads the
module fresh with the env var set beforehand."""
import importlib.util
import os
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient


def _load_api_gateway_app(monkeypatch, trusted_proxy_hops: str | None):
    if trusted_proxy_hops is None:
        monkeypatch.delenv("TRUSTED_PROXY_HOPS", raising=False)
    else:
        monkeypatch.setenv("TRUSTED_PROXY_HOPS", trusted_proxy_hops)

    spec = importlib.util.spec_from_file_location(
        "api_gateway_main_trusted_proxy_hops",
        os.path.join(os.path.dirname(__file__), "..", "main.py"),
    )
    api_gateway_main = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api_gateway_main)
    return api_gateway_main.app


def _sent_x_real_ip(app, headers: dict) -> str:
    client = TestClient(app)
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = httpx.Response(200, json={"success": True, "data": []})
        client.get("/api/v1/tenants/public/packages", headers=headers)
    _, kwargs = mock_request.call_args
    sent_headers = kwargs["headers"]
    return sent_headers.get("X-Real-IP") or sent_headers.get("x-real-ip")


def test_hops_zero_uses_direct_connection(monkeypatch) -> None:
    """Default (0, today's local behaviour): X-Real-IP is the direct
    connection, regardless of any X-Forwarded-For header."""
    app = _load_api_gateway_app(monkeypatch, "0")
    sent_ip = _sent_x_real_ip(app, {"X-Forwarded-For": "1.1.1.1, 2.2.2.2"})
    assert sent_ip == "testclient"  # starlette TestClient's direct connection host


def test_hops_unset_defaults_to_zero(monkeypatch) -> None:
    app = _load_api_gateway_app(monkeypatch, None)
    sent_ip = _sent_x_real_ip(app, {"X-Forwarded-For": "1.1.1.1, 2.2.2.2"})
    assert sent_ip == "testclient"


def test_hops_one_reads_rightmost_forwarded_entry(monkeypatch) -> None:
    """Behind one ALB hop: the real client IP is the entry the ALB appended
    itself — the rightmost entry of X-Forwarded-For."""
    app = _load_api_gateway_app(monkeypatch, "1")
    sent_ip = _sent_x_real_ip(app, {"X-Forwarded-For": "1.1.1.1, 2.2.2.2, 3.3.3.3"})
    assert sent_ip == "3.3.3.3"


def test_hops_one_falls_back_when_header_missing(monkeypatch) -> None:
    app = _load_api_gateway_app(monkeypatch, "1")
    sent_ip = _sent_x_real_ip(app, {})
    assert sent_ip == "testclient"


def test_hops_two_falls_back_when_header_too_short(monkeypatch) -> None:
    """Header has fewer entries than the configured hop count — fall back
    to the direct connection rather than trusting a short/spoofed header."""
    app = _load_api_gateway_app(monkeypatch, "2")
    sent_ip = _sent_x_real_ip(app, {"X-Forwarded-For": "1.1.1.1"})
    assert sent_ip == "testclient"
