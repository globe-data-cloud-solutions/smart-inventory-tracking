"""Unit tests for migration 090 / scripts/seed_permissions.py: TA setup grants
(Bugs 1-3, ClaudeE2EReviewBug.md) — position:manage, transfer_type:manage,
transfer_approval_rule:manage, adjustment:submit.

Reads the REAL seed_permissions.ROLE_PERMISSION_MATRIX (not a fabricated
mock) so these tests actually fail against the pre-fix matrix and pass only
once TA is granted — same pattern as test_renewal_requests.py's
_matrix_grant(). Mocked store/audit throughout — no real DB connection.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL",      "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("DATABASE_READ_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("JWT_SECRET",        "test-secret")
os.environ.setdefault("JWT_SECRET_KEY",    "test-secret")
os.environ.setdefault("ENVIRONMENT",       "local")

_SCRIPTS_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "scripts"))
if _SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, _SCRIPTS_ROOT)

from shared.permissions.middleware import check_permission
from shared.permissions.registry import PERMISSIONS

pytestmark = pytest.mark.asyncio

TENANT_ID = "aaaaaaaa-0000-0000-0000-000000000001"


def _user(role: str, tenant_id: str = TENANT_ID) -> MagicMock:
    user = MagicMock()
    user.role, user.tenant_id, user.warehouse_id = role, tenant_id, None
    return user


def _matrix_grant(role: str, action_id: str):
    """Mirrors the REAL seed_permissions.py matrix — None means RBAC_DENIED,
    matching what store.get_role_permission() would return from a freshly
    seeded DB for this (role, action) pair."""
    import seed_permissions
    grant_type = seed_permissions.ROLE_PERMISSION_MATRIX.get(role, {}).get(action_id)
    if grant_type is None:
        return None
    grant = MagicMock()
    grant.grant_type = grant_type
    return grant


async def _check(role: str, action) -> bool:
    user = _user(role)
    with patch("shared.permissions.middleware.get_role_permission",
               new=AsyncMock(side_effect=lambda r, a: _matrix_grant(r, a))), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()):
        result = await check_permission(user, action, {"tenant_id": TENANT_ID})
    return result.allowed


# position:manage / transfer_type:manage / transfer_approval_rule:manage:
# only SA held these before migration 090 — NM (one level below TA) is the
# "still denied" control for all three.

async def test_ta_can_manage_positions() -> None:
    assert await _check("TA", PERMISSIONS.POSITION_MANAGE) is True


async def test_nm_still_cannot_manage_positions() -> None:
    assert await _check("NM", PERMISSIONS.POSITION_MANAGE) is False


async def test_ta_can_manage_transfer_types() -> None:
    assert await _check("TA", PERMISSIONS.TRANSFER_TYPE_MANAGE) is True


async def test_nm_still_cannot_manage_transfer_types() -> None:
    assert await _check("NM", PERMISSIONS.TRANSFER_TYPE_MANAGE) is False


async def test_ta_can_manage_transfer_approval_rules() -> None:
    assert await _check("TA", PERMISSIONS.TRANSFER_APPROVAL_RULE_MANAGE) is True


async def test_nm_still_cannot_manage_transfer_approval_rules() -> None:
    assert await _check("NM", PERMISSIONS.TRANSFER_APPROVAL_RULE_MANAGE) is False


async def test_ta_can_view_transfer_approval_rules() -> None:
    """Necessary companion to :manage — upsert_approval_rules() builds its
    response by calling list_approval_rules() directly, re-running that
    function's own @require_permission(...VIEW) check (routers/transfer_types.py)."""
    assert await _check("TA", PERMISSIONS.TRANSFER_APPROVAL_RULE_VIEW) is True


async def test_nm_still_cannot_view_transfer_approval_rules() -> None:
    assert await _check("NM", PERMISSIONS.TRANSFER_APPROVAL_RULE_VIEW) is False


# adjustment:submit: NM/RM/WM already held this before migration 090, so the
# meaningful "still denied" control is AU (read-only Auditor role), not NM.

async def test_ta_can_submit_adjustments() -> None:
    assert await _check("TA", PERMISSIONS.ADJUSTMENT_SUBMIT) is True


async def test_au_still_cannot_submit_adjustments() -> None:
    assert await _check("AU", PERMISSIONS.ADJUSTMENT_SUBMIT) is False
