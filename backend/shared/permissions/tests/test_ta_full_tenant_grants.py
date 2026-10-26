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
