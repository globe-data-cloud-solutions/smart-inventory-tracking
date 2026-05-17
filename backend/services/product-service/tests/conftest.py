"""Fixtures for product-service unit tests.

No real DB or network — all infrastructure is mocked.
Integration tests (@pytest.mark.integration) run in CI against dev AWS RDS.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ── sys.modules isolation ─────────────────────────────────────────────────────
# Problem: `pytest backend/` puts BOTH service roots on sys.path and loads ALL
# conftest files before running any test.  inventory-service conftest runs first
# (alphabetical), caching `main`, `routers`, `schemas`, `dependencies`, etc.
# as inventory-service modules.  When this conftest runs next, `from main import app`
# would return the already-cached inventory-service app (wrong routes → 404).
#
# Fix: save the inventory-service module references, clear them, load the
# product-service app with product-service root first on sys.path, then RESTORE
# the inventory-service modules so that inventory-service tests that run later
# (dispatch, transfer) can still do `from schemas.inventory import LotSelection`
# and `from dependencies import get_current_user` correctly.

_product_root = str(Path(__file__).resolve().parent.parent)

# Module top-level names that exist in BOTH service roots and must be swapped.
_service_tops = {"main", "routers", "schemas", "services", "repositories", "dependencies"}

# 1. Save and evict inventory-service copies.
_saved_inv_modules: dict = {}
for _key in list(sys.modules):
    _top = _key.split(".")[0]
    if _top in _service_tops:
        _mod = sys.modules.get(_key)
        if _mod and "inventory-service" in (getattr(_mod, "__file__", None) or ""):
            _saved_inv_modules[_key] = sys.modules.pop(_key)

# 2. Promote product-service root to front of sys.path.
if _product_root in sys.path:
    sys.path.remove(_product_root)
sys.path.insert(0, _product_root)

# 3. Stub env vars BEFORE any shared module reads os.environ at import time.
os.environ.setdefault("DATABASE_URL",          "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("DATABASE_READ_URL",     "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("CELERY_BROKER_URL",     "redis://localhost:6379/1")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")
os.environ.setdefault("JWT_SECRET",            "x" * 64)

# 4. Import product-service modules while product-service root is first.
from main import app                            # noqa: E402  — product-service app
from shared.db.dependencies import get_db_session  # noqa: E402
from dependencies import get_current_user       # noqa: E402  — product-service version

# 5. Force-restore ALL inventory-service module refs that were evicted in step 1.
#    The imports in step 4 re-populated sys.modules with product-service versions
#    (e.g. sys.modules['schemas'] is now product-service/schemas/__init__.py).
#    We force-overwrite those back so that inventory-service tests that run later
#    in the same process can still do `from schemas.inventory import LotSelection`,
#    `from dependencies import get_current_user`, etc.
#    The product-service `app` and `get_current_user` are captured as local
#    variables above — they remain bound to the product-service objects regardless
#    of what sys.modules says after this point.
for _key, _mod in _saved_inv_modules.items():
    sys.modules[_key] = _mod  # force-overwrite — restore inventory-service version

# Restore sys.path order: inventory-service root first, product-service after.
if _product_root in sys.path:
    sys.path.remove(_product_root)
if _product_root not in sys.path:
    sys.path.append(_product_root)

from product_test_data import (              # noqa: F401  (re-export for fixture injection)
    TENANT_A, TENANT_B,
    TA_USER, SA_USER, WM_USER,
    VALID_BODY,
    mock_full_grant,
    _make_mock_db,
    _cap_db,
    _make_db_override,
)


# ── Client fixture ────────────────────────────────────────────────────────────

@pytest.fixture
def product_app():
    """The product-service FastAPI app — use for dependency_overrides in tests that
    need a custom DB or user. Do NOT do `from main import app` inside test bodies;
    by test-execution time sys.modules['main'] has been restored to inventory-service."""
    return app


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Test client with DB + user dependencies overridden."""
    db = _make_mock_db()
    app.dependency_overrides[get_db_session]   = _make_db_override(db)
    app.dependency_overrides[get_current_user] = lambda: TA_USER
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()
