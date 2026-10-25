"""Tripwire test for RB-1 sweep HOLE 8 (docs/reviews/2026-10-19-rb1-sweep.md).

HOLE 8 (tenant-service/routers/tenants.py:update_tenant_branding) is a latent
cross-tenant hole: the route never checks that the path tenant_id belongs to
the caller, but it is not exploitable today because no role in the permission
matrix holds tenant:upload_branding. This is deliberately left latent rather
than fixed here (see fix/rb1-holes).

This test is NOT a feature test — it is a tripwire. If someone later grants
tenant:upload_branding to any non-SA role, this test fails, which is the
intended signal to go fix the route's tenant-ownership check (the same way
HOLEs 1-7 were fixed) before shipping that grant.
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("DATABASE_READ_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("ENVIRONMENT", "local")

_SCRIPTS_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "scripts")
)
if _SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, _SCRIPTS_ROOT)

from seed_permissions import ROLE_PERMISSION_MATRIX  # noqa: E402 - sys.path/env setup above must run first

BRANDING_ACTION = "tenant:upload_branding"


def test_only_tenant_admin_and_sa_hold_branding_upload_permission() -> None:
    """HOLE 8 (update_tenant_branding path tenant) is now closed centrally: the
    permission middleware denies any non-SA/SYS caller whose required path
    {tenant_id} is another tenant (TENANT_ACCESS_DENIED). So TA may hold the
    grant for its own tenant. Any other non-SA role still needs review."""
    holders = sorted(
        role
        for role, grants in ROLE_PERMISSION_MATRIX.items()
        if role != "SA" and BRANDING_ACTION in grants
    )
    assert holders in ([], ["TA"]), (
        f"{BRANDING_ACTION} is held by non-SA role(s) {holders}. TA is covered by the "
        "path-tenant check in shared/permissions/middleware.py; any other role "
        "needs its own review before this grant."
    )


def test_branding_route_is_keyed_on_required_tenant_path() -> None:
    """The middleware path check only applies to a route with a required {tenant_id}
    path segment. Pin that for the branding route in the source, so the grant above
    stays safe if the route is ever re-declared."""
    tenants_src = os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "..",
        "services",
        "tenant-service",
        "routers",
        "tenants.py",
    )
    with open(tenants_src, encoding="utf-8") as fh:
        src = fh.read()
    assert '@router.patch("/{tenant_id}/branding"' in src
    assert "@require_permission(PERMISSIONS.TENANT_UPLOAD_BRANDING)" in src
