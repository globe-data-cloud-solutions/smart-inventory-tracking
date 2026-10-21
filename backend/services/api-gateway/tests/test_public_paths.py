"""Tests for api-gateway's public sign-up paths (S4): exact-match
UNAUTHENTICATED_PATHS entries pass without a token, everything else still
requires one, and X-Real-IP is always overwritten from the real connection."""

import importlib.util
import os
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def api_gateway_app():
    """Load the api-gateway main module and return the FastAPI app."""
    spec = importlib.util.spec_from_file_location(
        "api_gateway_main_public_paths",
        os.path.join(os.path.dirname(__file__), "..", "main.py"),
    )
    api_gateway_main = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api_gateway_main)
    return api_gateway_main.app


def test_public_packages_passes_without_token(api_gateway_app) -> None:
    client = TestClient(api_gateway_app)

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = httpx.Response(200, json={"success": True, "data": []})
        response = client.get("/api/v1/tenants/public/packages")

    assert response.status_code == 200
    mock_request.assert_called_once()


def test_public_signup_passes_without_token(api_gateway_app) -> None:
    client = TestClient(api_gateway_app)

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = httpx.Response(201, json={"success": True, "data": {}})
        response = client.post("/api/v1/tenants/public/signup", json={})

    assert response.status_code == 201
    mock_request.assert_called_once()


def test_forgot_password_passes_without_token(api_gateway_app) -> None:
    client = TestClient(api_gateway_app)

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = httpx.Response(202, json={"sent": True})
        response = client.post("/api/v1/auth/forgot-password", json={"email": "probe@example.com"})

    assert response.status_code == 202
    mock_request.assert_called_once()


def test_reset_password_passes_without_token(api_gateway_app) -> None:
    client = TestClient(api_gateway_app)

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = httpx.Response(200, json={"reset": True})
        response = client.post(
            "/api/v1/auth/reset-password",
            json={"token": "probe-token", "new_password": "Probe@2026"},
        )

    assert response.status_code == 200
    mock_request.assert_called_once()


def test_tenants_root_still_requires_token(api_gateway_app) -> None:
    """/api/v1/tenants/ (not /public/*) is unaffected — still 401 without a token."""
    client = TestClient(api_gateway_app)
    response = client.get("/api/v1/tenants/")
    assert response.status_code == 401


def test_incoming_x_real_ip_is_overwritten(api_gateway_app) -> None:
    """A caller cannot spoof the rate-limit key — X-Real-IP is always set from
    the actual connection, not trusted from the incoming request."""
    client = TestClient(api_gateway_app)

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = httpx.Response(200, json={"success": True, "data": []})
        client.get(
            "/api/v1/tenants/public/packages",
            headers={"X-Real-IP": "9.9.9.9"},
        )

    _, kwargs = mock_request.call_args
    sent_headers = kwargs["headers"]
    sent_ip = sent_headers.get("X-Real-IP") or sent_headers.get("x-real-ip")
    assert sent_ip != "9.9.9.9"
