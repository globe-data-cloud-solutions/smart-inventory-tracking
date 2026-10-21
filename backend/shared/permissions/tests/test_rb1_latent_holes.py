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


def test_no_non_sa_role_holds_branding_upload_permission() -> None:
    """SA holding it is safe (SA bypasses tenant-ownership checks by design) —
    only a non-SA grant would make HOLE 8 exploitable."""
    holders = [
        role
        for role, grants in ROLE_PERMISSION_MATRIX.items()
        if role != "SA" and BRANDING_ACTION in grants
    ]
    assert holders == [], (
        f"{BRANDING_ACTION} is now granted to non-SA role(s) {holders}, but "
        "tenants.py:update_tenant_branding (HOLE 8, docs/reviews/2026-10-19-rb1-sweep.md) "
        "still has no tenant-ownership check on its path tenant_id. Add that check "
        "(same pattern as _resolve_and_authorize_tenant_id in tenants.py) before "
        "shipping this grant."
    )
