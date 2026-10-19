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
# Several backend services share top-level module names (`main`, `routers`,
# `schemas`, `services`, `repositories`, `dependencies`) — each service root is
# only added to sys.path by its OWN conftest.py, so whichever service's
# conftest ran first in this pytest session can leave its modules cached under
# these bare names for the rest of the process, shadowing a sibling service's
# same-named modules. A bare `from main import app` elsewhere in the process
# would then resolve to the wrong service's `main.py`.
#
# Fix: evict EVERY sys.modules entry for these top-level names that isn't
# product-service's own copy, promote product-service's root to the front of
# sys.path, import fresh, then restore whatever was evicted. A name that had
# nothing saved (nobody had imported it yet in this process) is LEFT as
# product-service's freshly-imported version rather than popped.

_product_root = str(Path(__file__).resolve().parent.parent)

# Module top-level names that exist in multiple service roots and must be swapped.
_service_tops = {"main", "routers", "schemas", "services", "repositories", "dependencies"}

# 1. Save and evict every non-product-service copy (any service, not only
#    inventory-service — e.g. api-gateway's `main.py` is earlier on sys.path
#    than product-service's and would otherwise win).
_saved_other_modules: dict = {}
for _key in list(sys.modules):
    _top = _key.split(".")[0]
    if _top in _service_tops:
        _mod = sys.modules.get(_key)
        _file = getattr(_mod, "__file__", None) or ""
        if _mod and "product-service" not in _file:
            _saved_other_modules[_key] = sys.modules.pop(_key)

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
from dependencies import get_db_session  # noqa: E402
from dependencies import get_current_user       # noqa: E402  — product-service version

# Collection-time guard: fail loudly (not with a mystifying 401 at test-execution
# time) if the eviction/promotion above somehow didn't win — e.g. a future new
# editable-installed service shadows product-service's own `dependencies.py`.
_gcu_file = get_current_user.__code__.co_filename
_gds_file = get_db_session.__code__.co_filename
if "product-service" not in _gcu_file or "product-service" not in _gds_file:
    raise RuntimeError(
        "product-service conftest: get_current_user/get_db_session resolved to "
        f"the wrong service module — get_current_user={_gcu_file!r}, "
        f"get_db_session={_gds_file!r}"
    )
# Route-path introspection (checking r.path on app.routes) broke on newer
# FastAPI/Starlette: app.include_router() now wraps each included router as
# a fastapi.routing._IncludedRouter entry in app.routes, which has no .path
# attribute (getattr returns None) — the routes are still registered and
# resolve correctly at request time, this check just can't see them anymore.
# app.title is version-agnostic and was already a stable per-service
# identifier (set in each service's main.py), so use that instead.
if app.title != "SMART Product Service":
    raise RuntimeError(
        f"product-service conftest: `app.title` is {app.title!r} — it is not "
        "the product-service app."
    )

# 5. Undo every sys.modules change the import in step 4 made under a
#    _service_tops name: restore whatever was saved in step 1. A name that had
#    nothing saved (nobody had imported it yet in this process) is LEFT as
#    product-service's freshly-imported version — product-service's own test
#    files never do a bare `from schemas import X`/`from services import X`
#    (they go through `product_test_data`'s captured `app`/`get_current_user`/
#    `get_db_session` instead), so leaving these behind cannot shadow anything
#    product-service's own tests need; a sibling service's conftest that needs
#    its own copy back will evict-and-restore it from here when IT runs.
#    The product-service `app`, `get_current_user`, `get_db_session` are
#    captured as local variables above — they remain bound to the
#    product-service objects regardless of what sys.modules says after this.
for _key in list(sys.modules):
    _top = _key.split(".")[0]
    if _top not in _service_tops:
        continue
    if _key in _saved_other_modules:
        sys.modules[_key] = _saved_other_modules.pop(_key)
    # else: leave product-service's freshly-imported version in place.
for _key, _mod in _saved_other_modules.items():
    sys.modules[_key] = _mod

# Demote product-service root to the end of sys.path rather than removing it:
# product_test_data (below) still needs it, and any sibling service's conftest
# that runs later in this session appends ITS root afterward too — so whichever
# conftest ran first keeps earliest (and thus winning) position among the
# appended roots for any future ambiguous bare import.
if _product_root in sys.path:
    sys.path.remove(_product_root)
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

# Inject the product-service get_db_session into product_test_data so that
# test_products.py can import it from there.  By this point sys.modules has been
# restored to inventory-service versions, so `from dependencies import get_db_session`
# in test_products.py would return the wrong object.  product_test_data is a stable
# intermediate that survives sys.modules restoration.
import product_test_data as _ptd
_ptd.get_db_session = get_db_session  # type: ignore[attr-defined]
_ptd.get_current_user = get_current_user  # type: ignore[attr-defined]


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
