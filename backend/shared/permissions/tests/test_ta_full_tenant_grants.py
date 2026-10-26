"""TA holds every tenant-scoped action, and no platform-only or system-only one.

Pins the grant so a new tenant action cannot silently go unassigned to TA, and a
platform action cannot leak to TA. Read-only classification is out of scope here.
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

from seed_permissions import ROLE_PERMISSION_MATRIX

from shared.permissions.registry import ALL_PERMISSIONS

TA_GRANTS = ROLE_PERMISSION_MATRIX["TA"]


def _scope(perm) -> set[str]:
    return set(perm.abac)


def test_ta_holds_every_tenant_scoped_action() -> None:
    missing = sorted(
        p.id
        for p in ALL_PERMISSIONS
        if "platform_only" not in _scope(p)
        and "system_only" not in _scope(p)
        and p.id != "system:health_check"
        and p.id not in TA_GRANTS
    )
    assert missing == [], f"tenant-scoped actions not granted to TA: {missing}"


def test_ta_holds_no_platform_or_system_action() -> None:
    leaked = sorted(
        p.id
        for p in ALL_PERMISSIONS
        if ("platform_only" in _scope(p) or "system_only" in _scope(p)) and p.id in TA_GRANTS
    )
    assert leaked == [], f"platform/system-only actions granted to TA: {leaked}"


def test_moved_plan_and_contact_routes_use_platform_actions() -> None:
    """Plan and contact writes are SA-only by permission, not only by handler code."""
    by_id = {p.id: p for p in ALL_PERMISSIONS}
    for action in ("plan:change", "billing:view", "platform:contact_edit"):
        assert "platform_only" in _scope(by_id[action]), action
        assert action not in TA_GRANTS, action


def test_tenant_admin_user_routes_use_platform_only_permissions() -> None:
    """GET/PATCH /{tenant_id}/admin-user are SA-only. They sat on TENANT_MANAGE,
    a tenant-scoped action TA holds, with only the in-handler SA check in the
    way. They now use platform_only actions, so the permission layer refuses a
    TA before the handler runs (the handler check stays as a second layer)."""
    from shared.permissions.registry import PERMISSIONS

    src_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "..",
        "services",
        "tenant-service",
        "routers",
        "tenants.py",
    )
    with open(src_path, encoding="utf-8") as fh:
        src = fh.read()

    get_route = '@router.get("/{tenant_id}/admin-user"'
    patch_route = '@router.patch("/{tenant_id}/admin-user"'
    for route, perm in (
        (get_route, "@require_permission(PERMISSIONS.TENANT_REGISTRY_VIEW"),
        (patch_route, "@require_permission(PERMISSIONS.TENANT_PROFILE_EDIT"),
    ):
        i = src.index(route)
        decorator_line = src[i:].split("\n")[1]
        assert decorator_line.startswith(perm), (route, decorator_line)

    for action in (PERMISSIONS.TENANT_REGISTRY_VIEW, PERMISSIONS.TENANT_PROFILE_EDIT):
        assert "platform_only" in _scope(action), action.id
        assert action.id not in TA_GRANTS
