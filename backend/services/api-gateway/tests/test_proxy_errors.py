"""Tests for api-gateway proxy error handling (503/504 for unreachable services)."""

import importlib.util
import os
from unittest.mock import AsyncMock, patch

import time

import httpx
import pytest
from fastapi.testclient import TestClient
from jose import jwt


@pytest.fixture
def valid_jwt_token():
    """Generate a valid HS256 JWT token for testing."""
    secret = os.environ.get("JWT_SECRET", "test-secret-key-at-least-32-chars")
    payload = {
        "sub": "test-user-id",
        "role": "SA",
        "tenant_id": "test-tenant-id",
        "iat": int(time.time()),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.fixture
def api_gateway_app():
    """Load the api-gateway main module and return the FastAPI app."""
    # Avoid import collision — use spec_from_file_location
    spec = importlib.util.spec_from_file_location(
        "api_gateway_main",
        os.path.join(os.path.dirname(__file__), "..", "main.py"),
    )
    api_gateway_main = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api_gateway_main)
    return api_gateway_main.app


def test_proxy_returns_503_on_connect_error(api_gateway_app, valid_jwt_token):
    """When a downstream service is unreachable, return 503 SERVICE_UNAVAILABLE."""
    client = TestClient(api_gateway_app)

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.side_effect = httpx.ConnectError("Connection refused")

        response = client.get(
            "/api/v1/tenants/test",
            headers={"Authorization": f"Bearer {valid_jwt_token}"},
        )

        assert response.status_code == 503
        data = response.json()
        assert data["success"] is False
        assert data["error"]["code"] == "SERVICE_UNAVAILABLE"
        assert "unavailable" in data["error"]["message"]


def test_proxy_returns_504_on_timeout(api_gateway_app, valid_jwt_token):
    """When a downstream service times out, return 504 UPSTREAM_TIMEOUT."""
    client = TestClient(api_gateway_app)

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.side_effect = httpx.TimeoutException("Request timed out")

        response = client.get(
            "/api/v1/tenants/test",
            headers={"Authorization": f"Bearer {valid_jwt_token}"},
        )

        assert response.status_code == 504
        data = response.json()
        assert data["success"] is False
        assert data["error"]["code"] == "UPSTREAM_TIMEOUT"
        assert "timed out" in data["error"]["message"]


def test_proxy_returns_401_without_token(api_gateway_app):
    """Missing JWT token returns 401 (unchanged behaviour)."""
    client = TestClient(api_gateway_app)

    response = client.get("/api/v1/tenants/test")

    assert response.status_code == 401
    assert "Missing token" in response.json()["detail"]


def test_proxy_returns_404_for_unknown_route(api_gateway_app, valid_jwt_token):
    """Unknown route returns 404 (unchanged behaviour)."""
    client = TestClient(api_gateway_app)

    response = client.get(
        "/api/v1/unknown-service/test",
        headers={"Authorization": f"Bearer {valid_jwt_token}"},
    )

    assert response.status_code == 404
    assert "Route not found" in response.json()["detail"]
