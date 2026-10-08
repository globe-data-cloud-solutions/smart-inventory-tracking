"""Tests for api-gateway's token-revocation check: a revoked JWT (per
shared.cache.token_revocation.is_token_revoked) is rejected with 401
TOKEN_REVOKED even though its signature is valid; a non-revoked token is
proxied as before; public paths never run the check at all."""
import importlib.util
import os
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from jose import jwt

_ALG = "HS256"


@pytest.fixture
def api_gateway_app():
    spec = importlib.util.spec_from_file_location(
        "api_gateway_main_token_revocation",
        os.path.join(os.path.dirname(__file__), "..", "main.py"),
    )
    api_gateway_main = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api_gateway_main)
    return api_gateway_main


def _token(**extra) -> str:
    secret = os.environ.get("JWT_SECRET") or os.environ.get("JWT_SECRET_KEY") or "test-secret"
    payload = {"sub": "user-1", "tenant_id": "tenant-1", "role": "TA", "iat": 1000}
    payload.update(extra)
    return jwt.encode(payload, secret, algorithm=_ALG)


def test_revoked_token_returns_401(api_gateway_app) -> None:
    client = TestClient(api_gateway_app.app)

    with patch.object(api_gateway_app, "is_token_revoked", new=AsyncMock(return_value=True)):
        response = client.get(
            "/api/v1/tenants/",
            headers={"Authorization": f"Bearer {_token()}"},
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "TOKEN_REVOKED"


def test_non_revoked_token_is_proxied(api_gateway_app) -> None:
    client = TestClient(api_gateway_app.app)

    with patch.object(api_gateway_app, "is_token_revoked", new=AsyncMock(return_value=False)), \
         patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = httpx.Response(200, json={"success": True, "data": []})
        response = client.get(
            "/api/v1/tenants/",
            headers={"Authorization": f"Bearer {_token()}"},
        )

    assert response.status_code == 200
    mock_request.assert_called_once()


def test_public_path_never_checks_revocation(api_gateway_app) -> None:
    client = TestClient(api_gateway_app.app)

    with patch.object(api_gateway_app, "is_token_revoked", new=AsyncMock()) as mock_check, \
         patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = httpx.Response(200, json={"success": True, "data": []})
        response = client.get("/api/v1/tenants/public/packages")

    assert response.status_code == 200
    mock_check.assert_not_called()
