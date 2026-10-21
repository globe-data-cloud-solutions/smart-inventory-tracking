from __future__ import annotations

import os
import sys
from pathlib import Path

# Must be set before shared.db.session is imported (it reads DATABASE_URL at module level)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("DATABASE_READ_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-for-unit-tests")
os.environ.setdefault("ENVIRONMENT", "local")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/1")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")

from dataclasses import dataclass
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

# ── sys.modules isolation ─────────────────────────────────────────────────────
# Several backend services share top-level module names (`main`, `routers`,
# `schemas`, `services`, `repositories`, `dependencies`) — each service root is
# only added to sys.path by its OWN conftest.py, so whichever service's
# conftest ran first in this pytest session can leave its modules cached under
# these bare names for the rest of the process, shadowing a sibling service's
# same-named modules. A bare `from main import app` elsewhere in the process
# would then resolve to the wrong service's `main.py`.
#
# Fix: evict every sys.modules entry for these top-level names that isn't
# inventory-service's own copy, promote inventory-service's root to the front
# of sys.path, import fresh, then restore whatever was evicted. A name that
# had nothing saved (nobody had imported it yet in this process) is LEFT as
# inventory-service's freshly-imported version rather than popped — inventory's
# own `main` import chain already transitively imports inventory's own
# `schemas.inventory`, `schemas.analytics`, `services.inventory_service`, and
# `services.state_machine` (via routers → services → schemas), so those dotted
# submodule entries are already correct for inventory-service's later test
# files to find directly in sys.modules, regardless of what a sibling
# service's conftest does to the bare `schemas`/`services` package names.

_inventory_root = str(Path(__file__).resolve().parent.parent)
_service_tops = {"main", "routers", "schemas", "services", "repositories", "dependencies"}

_saved_other_modules: dict = {}
for _key in list(sys.modules):
    _top = _key.split(".")[0]
    if _top in _service_tops:
        _mod = sys.modules.get(_key)
        _file = getattr(_mod, "__file__", None) or ""
        if _mod and "inventory-service" not in _file:
            _saved_other_modules[_key] = sys.modules.pop(_key)

if _inventory_root in sys.path:
    sys.path.remove(_inventory_root)
sys.path.insert(0, _inventory_root)

from main import app  # noqa: E402 - sys.path/sys.modules setup above must run first
from dependencies import get_current_user, get_db_session  # noqa: E402 - sys.path/sys.modules setup above must run first

# Collection-time guard: fail loudly (not with a mystifying 401 at test-execution
# time) if the eviction/promotion above somehow didn't win.
_gcu_file = get_current_user.__code__.co_filename
_gds_file = get_db_session.__code__.co_filename
if "inventory-service" not in _gcu_file or "inventory-service" not in _gds_file:
    raise RuntimeError(
        "inventory-service conftest: get_current_user/get_db_session resolved to "
        f"the wrong service module — get_current_user={_gcu_file!r}, "
        f"get_db_session={_gds_file!r}"
    )
if not any(getattr(r, "path", "").startswith("/api/v1/inventory") for r in app.routes):
    raise RuntimeError(
        "inventory-service conftest: `app` has no /api/v1/inventory route — it "
        f"is not the inventory-service app. Routes: {[getattr(r, 'path', None) for r in app.routes]}"
    )

for _key in list(sys.modules):
    _top = _key.split(".")[0]
    if _top not in _service_tops:
        continue
    if _key in _saved_other_modules:
        sys.modules[_key] = _saved_other_modules.pop(_key)
    # else: leave inventory-service's freshly-imported version in place —
    # see the module-level comment above for why that's safe.
for _key, _mod in _saved_other_modules.items():
    sys.modules[_key] = _mod

# Demote inventory-service root to the end of sys.path rather than removing
# it: a later test file in this directory (e.g. a stable intermediate module,
# same pattern as product-service's product_test_data) may still need it, and
# any sibling service's conftest that runs later in this session appends ITS
# root afterward too — so whichever conftest ran first keeps earliest (and
# thus winning) position among the appended roots for any future ambiguous
# bare import.
if _inventory_root in sys.path:
    sys.path.remove(_inventory_root)
sys.path.append(_inventory_root)


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
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def inv_app():
    """The inventory-service FastAPI app captured above — use this (not a fresh
    `from main import app`) for dependency_overrides in test bodies, since a
    fresh import in a test module may resolve to a different service's `main`
    depending on sys.path state at that module's own import time."""
    return app


@pytest.fixture
def inv_get_current_user():
    """The inventory-service get_current_user captured above — see inv_app."""
    return get_current_user


@pytest.fixture
def wm_user():
    return WM_STUB


@pytest.fixture
def au_user():
    return _StubUser("u-au", TENANT_A, "AU")


@pytest.fixture
def other_tenant_user():
    return _StubUser("u-ot", "99999999-0000-0000-0000-000000000001", "WM", warehouse_id=WAREHOUSE_A)
