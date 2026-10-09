"""GET /static/uploads/{path} in S3 mode (main.py's serve_upload route).

main.py decides disk-mount vs S3-proxy at import time based on STORAGE_BACKEND,
and the shared conftest has already imported+cached product-service's `main`
under STORAGE_BACKEND=local for the rest of the suite. To exercise the S3
branch without disturbing that cached app, this test loads a second, throwaway
copy of main.py under a private module name with STORAGE_BACKEND=s3 set first.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

_PRODUCT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def s3_app(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("STORAGE_S3_BUCKET", "smart-dev-attachments")

    spec = importlib.util.spec_from_file_location(
        "_main_s3_probe", _PRODUCT_ROOT / "main.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(_PRODUCT_ROOT))
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    finally:
        sys.path.remove(str(_PRODUCT_ROOT))

    module._storage.get = AsyncMock(return_value=None)
    yield module


@pytest.mark.asyncio
async def test_rejects_dotdot_path(s3_app) -> None:
    # httpx/browsers normalize a literal ".." out of the URL before it is sent,
    # so this exercises the handler's own guard via the percent-encoded form,
    # which arrives at the route unmodified.
    async with AsyncClient(
        transport=ASGITransport(app=s3_app.app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/static/uploads/%2e%2e/secret")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_returns_404_when_missing(s3_app) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=s3_app.app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/static/uploads/products/missing.jpg")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_returns_bytes_with_content_type_and_cache_header(s3_app) -> None:
    s3_app._storage.get = AsyncMock(return_value=(b"image-bytes", "image/png"))
    async with AsyncClient(
        transport=ASGITransport(app=s3_app.app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/static/uploads/products/photo.png")
    assert resp.status_code == 200
    assert resp.content == b"image-bytes"
    assert resp.headers["content-type"] == "image/png"
    assert resp.headers["cache-control"] == "public, max-age=86400"
