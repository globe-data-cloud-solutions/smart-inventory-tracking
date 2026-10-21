"""Regression tests for the RB-1 sweep's shared middleware fix
(docs/reviews/2026-10-19-rb1-sweep.md, root cause of HOLEs 1-3): a route's
real {tenant_id} path value was captured as resource["target_tenant_id"]
but never compared to anything. check_permission() now denies a non-SA/SYS
caller whose path tenant_id (by UUID or by slug) differs from their own.

Also proves the fix does NOT apply to an Optional[...] = Query(None)
tenant_id override (e.g. GET .../expiry-settings?tenant_id=<other>), which
routes already resolve safely via effective_tenant_id() and must keep
returning 200 for a mismatched override from a non-SA caller, not 403.
"""

from __future__ import annotations

import os
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("DATABASE_READ_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("ENVIRONMENT", "local")

pytestmark = pytest.mark.asyncio

TENANT_A = "aaaaaaaa-0000-0000-0000-000000000001"
TENANT_B = "bbbbbbbb-0000-0000-0000-000000000002"

_FULL_GRANT = patch(
    "shared.permissions.middleware.get_role_permission",
    new=AsyncMock(return_value=MagicMock(grant_type="FULL")),
)
_NO_AUDIT = patch("shared.permissions.middleware.audit_log", new=AsyncMock())


def _user(role: str, tenant_id: str | None) -> MagicMock:
    u = MagicMock()
    u.role, u.tenant_id, u.warehouse_id, u.region_id = role, tenant_id, None, None
    return u


class TestCheckPermissionTargetTenant:
    """Direct check_permission() tests — same style as test_ta_setup_grants.py."""

    async def test_non_sa_denied_when_target_tenant_differs(self) -> None:
        from shared.permissions.middleware import check_permission
        from shared.permissions.registry import PERMISSIONS

        with _FULL_GRANT, _NO_AUDIT:
            result = await check_permission(
                _user("TA", TENANT_A),
                PERMISSIONS.TENANT_VIEW,
                resource={
                    "tenant_id": TENANT_A,
                    "target_tenant_id": TENANT_B,
                    "_tenant_id_from_path": True,
                },
                db=None,
            )
        assert result.allowed is False
        assert result.reason == "TENANT_ACCESS_DENIED"

    async def test_non_sa_allowed_when_target_tenant_matches(self) -> None:
        from shared.permissions.middleware import check_permission
        from shared.permissions.registry import PERMISSIONS

        with _FULL_GRANT, _NO_AUDIT:
            result = await check_permission(
                _user("TA", TENANT_A),
                PERMISSIONS.TENANT_VIEW,
                resource={
                    "tenant_id": TENANT_A,
                    "target_tenant_id": TENANT_A,
                    "_tenant_id_from_path": True,
                },
                db=None,
            )
        assert result.allowed is True

    async def test_sa_allowed_regardless_of_target_tenant(self) -> None:
        from shared.permissions.middleware import check_permission
        from shared.permissions.registry import PERMISSIONS

        with _FULL_GRANT, _NO_AUDIT:
            result = await check_permission(
                _user("SA", None),
                PERMISSIONS.TENANT_VIEW,
                resource={
                    "tenant_id": None,
                    "target_tenant_id": TENANT_B,
                    "_tenant_id_from_path": True,
                },
                db=None,
            )
        assert result.allowed is True

    async def test_sys_allowed_regardless_of_target_tenant(self) -> None:
        from shared.permissions.middleware import check_permission
        from shared.permissions.registry import PERMISSIONS

        with _FULL_GRANT, _NO_AUDIT:
            result = await check_permission(
                _user("SYS", None),
                PERMISSIONS.TENANT_VIEW,
                resource={
                    "tenant_id": None,
                    "target_tenant_id": TENANT_B,
                    "_tenant_id_from_path": True,
                },
                db=None,
            )
        assert result.allowed is True

    async def test_slug_target_resolves_before_comparing(self) -> None:
        """A non-UUID target_tenant_id (a slug) must be resolved via the tenants
        table before comparing — a slug that resolves to the caller's own
        tenant is allowed."""
        from shared.permissions.middleware import check_permission
        from shared.permissions.registry import PERMISSIONS

        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(fetchone=MagicMock(return_value=MagicMock(id=TENANT_A)))
        )

        with _FULL_GRANT, _NO_AUDIT:
            result = await check_permission(
                _user("TA", TENANT_A),
                PERMISSIONS.TENANT_VIEW,
                resource={
                    "tenant_id": TENANT_A,
                    "target_tenant_id": "tenant-a-slug",
                    "_tenant_id_from_path": True,
                },
                db=db,
            )
        assert result.allowed is True


class TestRequirePermissionSignatureDistinguishesPathFromQuery:
    """The decorator must only enforce the path-tenant_id check for a REQUIRED
    tenant_id parameter (a real {tenant_id} path segment) — never for an
    Optional[...] = Query(None) override, which routes already handle safely."""

    async def test_required_tenant_id_mismatch_is_denied(self) -> None:
        from shared.permissions.middleware import require_permission
        from shared.permissions.registry import PERMISSIONS
        from fastapi import HTTPException

        @require_permission(PERMISSIONS.TENANT_VIEW)
        async def fake_route(tenant_id: UUID, user=None, db=None):
            return "ok"

        with _FULL_GRANT, _NO_AUDIT:
            with pytest.raises(HTTPException) as exc:
                await fake_route(tenant_id=UUID(TENANT_B), user=_user("TA", TENANT_A), db=None)
        assert exc.value.status_code == 403
        assert exc.value.detail["code"] == "TENANT_ACCESS_DENIED"

    async def test_optional_tenant_id_override_mismatch_is_not_denied(self) -> None:
        """Mirrors lots.py's get_expiry_settings / put_expiry_settings pattern:
        tenant_id: Optional[UUID] = None is a caller override, always ignored
        for non-SA — must keep succeeding, not become a new 403."""
        from shared.permissions.middleware import require_permission
        from shared.permissions.registry import PERMISSIONS

        @require_permission(PERMISSIONS.TENANT_VIEW)
        async def fake_route(tenant_id: Optional[UUID] = None, user=None, db=None):
            return "ok"

        with _FULL_GRANT, _NO_AUDIT:
            result = await fake_route(tenant_id=UUID(TENANT_B), user=_user("TA", TENANT_A), db=None)
        assert result == "ok"


class TestAuditAttributionDecoupledFromEnforcement:
    """Coordinator correction (session 17 regression): target_tenant_id must keep
    being set for ANY tenant_id kwarg — path or query override — so audit_log()
    can still attribute an SA's decision on an override route to the target
    tenant. Enforcement reads a SEPARATE "_tenant_id_from_path" flag; the two
    must never be entangled into one condition again."""

    async def test_sa_override_route_audit_still_attributed_to_target_tenant(self) -> None:
        from shared.permissions.middleware import require_permission
        from shared.permissions.registry import PERMISSIONS

        captured_resource: dict = {}

        async def _capture_audit(user, action, resource, decision, reason=""):
            captured_resource.update(resource)

        @require_permission(PERMISSIONS.TENANT_VIEW)
        async def fake_override_route(tenant_id: Optional[UUID] = None, user=None, db=None):
            return "ok"

        with (
            _FULL_GRANT,
            patch(
                "shared.permissions.middleware.audit_log", new=AsyncMock(side_effect=_capture_audit)
            ),
        ):
            result = await fake_override_route(
                tenant_id=UUID(TENANT_B), user=_user("SA", None), db=None
            )

        assert result == "ok"
        # target_tenant_id must still be set (audit attribution) even though this
        # is an optional query override, not a required path param.
        assert captured_resource.get("target_tenant_id") == str(UUID(TENANT_B))
        # ...but the enforcement-only flag must NOT be set for this route shape.
        assert "_tenant_id_from_path" not in captured_resource

    async def test_required_path_route_sets_from_path_flag(self) -> None:
        from shared.permissions.middleware import require_permission
        from shared.permissions.registry import PERMISSIONS

        captured_resource: dict = {}

        async def _capture_audit(user, action, resource, decision, reason=""):
            captured_resource.update(resource)

        @require_permission(PERMISSIONS.TENANT_VIEW)
        async def fake_path_route(tenant_id: UUID, user=None, db=None):
            return "ok"

        with (
            _FULL_GRANT,
            patch(
                "shared.permissions.middleware.audit_log", new=AsyncMock(side_effect=_capture_audit)
            ),
        ):
            await fake_path_route(tenant_id=UUID(TENANT_A), user=_user("TA", TENANT_A), db=None)

        assert captured_resource.get("target_tenant_id") == str(UUID(TENANT_A))
        assert captured_resource.get("_tenant_id_from_path") is True


class TestCaseInsensitiveTenantComparison:
    """The mismatch check must not false-positive on casing differences between
    the JWT's tenant_id and the path/slug-resolved value."""

    async def test_same_tenant_uppercase_path_uuid_is_allowed(self) -> None:
        """tenants.py's get_tenant/get_approval_rules/put_approval_rules type
        tenant_id as plain `str` (to also accept a slug), so — unlike a route
        typed `tenant_id: UUID`, where FastAPI/Python's uuid module always
        normalizes to lowercase — the ORIGINAL casing of the path string
        reaches the wrapper unchanged and must be handled explicitly."""
        from shared.permissions.middleware import require_permission
        from shared.permissions.registry import PERMISSIONS

        @require_permission(PERMISSIONS.TENANT_VIEW)
        async def fake_route(tenant_id: str, user=None, db=None):
            return "ok"

        uppercase_tenant_a = TENANT_A.upper()
        with _FULL_GRANT, _NO_AUDIT:
            result = await fake_route(
                tenant_id=uppercase_tenant_a, user=_user("TA", TENANT_A), db=None
            )
        assert result == "ok"

    async def test_same_tenant_uppercase_slug_resolved_id_is_allowed(self) -> None:
        from shared.permissions.middleware import check_permission
        from shared.permissions.registry import PERMISSIONS

        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(fetchone=MagicMock(return_value=MagicMock(id=TENANT_A.upper())))
        )

        with _FULL_GRANT, _NO_AUDIT:
            result = await check_permission(
                _user("TA", TENANT_A),
                PERMISSIONS.TENANT_VIEW,
                resource={
                    "tenant_id": TENANT_A,
                    "target_tenant_id": "tenant-a-slug",
                    "_tenant_id_from_path": True,
                },
                db=db,
            )
        assert result.allowed is True
