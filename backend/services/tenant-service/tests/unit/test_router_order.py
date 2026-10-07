"""Regression test for the S10 router-registration-order bug: tenants.router's
fixed /platform/addons[...] paths were shadowed by billing.router's
parameterised /{tenant_id}/addons when billing.router was registered first —
Starlette matches routes in registration order across the whole app, not
per-router (see CLAUDE.md §15 S10, main.py comment).

This asserts the ACTUAL ASGI routing table, not a handler function called
directly — calling get_platform_addons() directly would pass trivially
regardless of router order and would not catch this regression.

DATABASE_URL and JWT_SECRET must be set before any router import.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("DATABASE_URL",      "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("DATABASE_READ_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("JWT_SECRET",        "test-secret")
os.environ.setdefault("JWT_SECRET_KEY",    "test-secret")
os.environ.setdefault("ENVIRONMENT",       "local")

_TENANT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _TENANT_ROOT not in sys.path:
    sys.path.insert(0, _TENANT_ROOT)

import pytest
from starlette.routing import Match


@pytest.mark.unit
def test_platform_addons_resolves_to_tenants_router_not_billing() -> None:
    """GET /api/v1/tenants/platform/addons must match tenants.py's fixed
    /platform/addons route, not billing.py's parameterised
    /{tenant_id}/addons (which would otherwise match first with
    tenant_id="platform" and fail UUID parsing on any request)."""
    from main import app

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/tenants/platform/addons",
        "path_params": {},
    }

    matched_route = None
    for route in app.routes:
        match, _ = route.matches(scope)
        if match == Match.FULL:
            matched_route = route
            break

    assert matched_route is not None, "no route matched /api/v1/tenants/platform/addons at all"
    assert matched_route.endpoint.__name__ == "get_platform_addons", (
        f"expected tenants.py's get_platform_addons to match first, got "
        f"{matched_route.endpoint.__name__!r} from {matched_route.endpoint.__module__!r} "
        f"(router registration order regression — tenants.router must precede billing.router in main.py)"
    )


@pytest.mark.unit
def test_tenant_addons_still_resolves_to_billing_router() -> None:
    """Sanity check the fix didn't break the legitimate parameterised route:
    GET /api/v1/tenants/{tenant_id}/addons must still match billing.py's
    get_tenant_addons for an actual tenant UUID."""
    from main import app

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/tenants/aaaaaaaa-0000-0000-0000-000000000001/addons",
        "path_params": {},
    }

    matched_route = None
    for route in app.routes:
        match, _ = route.matches(scope)
        if match == Match.FULL:
            matched_route = route
            break

    assert matched_route is not None
    assert matched_route.endpoint.__name__ == "get_tenant_addons"
