from __future__ import annotations

import os

# Must be set before shared.db.session is imported (it reads DATABASE_URL at module level)
os.environ.setdefault("DATABASE_URL",          "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("DATABASE_READ_URL",     "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("JWT_SECRET",            "test-secret-for-unit-tests")
os.environ.setdefault("JWT_SECRET_KEY",        "test-secret-for-unit-tests")
os.environ.setdefault("ENVIRONMENT",           "local")
os.environ.setdefault("CELERY_BROKER_URL",     "redis://localhost:6379/1")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")

from dataclasses import dataclass
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from dependencies import get_current_user, get_db_session


@dataclass
class _StubUser:
    user_id: str
    tenant_id: str
    role: str
    warehouse_id: Optional[str] = None
    region_id: Optional[str] = None


TENANT_A = "10000000-0000-0000-0000-000000000001"
WAREHOUSE_A = "20000000-0000-0000-0000-000000000001"

WM_STUB = _StubUser("u-wm", TENANT_A, "WM", warehouse_id=WAREHOUSE_A)


def _make_mock_db() -> AsyncMock:
    """Minimal AsyncSession mock — no real DB needed for unit tests."""
    db = AsyncMock()
    default = MagicMock()
    default.fetchone.return_value = None
    default.scalar.return_value = 0
    db.execute = AsyncMock(return_value=default)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _db_override(db: AsyncMock):
    async def _gen():
        yield db
    return _gen


@pytest.fixture
async def client():
    """Default test client — injects WM_STUB user and mock DB."""
    db = _make_mock_db()
    app.dependency_overrides[get_current_user] = lambda: WM_STUB
    app.dependency_overrides[get_db_session] = _db_override(db)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def wm_user():
    return WM_STUB


@pytest.fixture
def au_user():
    return _StubUser("u-au", TENANT_A, "AU")


@pytest.fixture
def other_tenant_user():
    return _StubUser("u-ot", "99999999-0000-0000-0000-000000000001", "WM",
                     warehouse_id=WAREHOUSE_A)
