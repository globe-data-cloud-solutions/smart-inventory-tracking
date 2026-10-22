"""RB-2 (2026-10-22): fail-closed node scope and RM region scope.

- G1: a facility-scoped user with no node is denied on warehouse-scoped resources.
- G3: RM is facility-scoped, so an RM is limited to its region's subtree.
- resolve_node_scope(): the shared read-side resolver used by the tenant-only
  views and by report queries.

Database calls are mocked; the node subtree is patched per test.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.permissions.hierarchy_service import (
    FACILITY_SCOPED_ROLES,
    TENANT_WIDE_ROLES,
    resolve_node_scope,
)
from shared.permissions.middleware import check_permission
from shared.permissions.registry import PERMISSIONS

TENANT = "10000000-0000-0000-0000-000000000001"
NODE_A = "20000000-0000-0000-0000-00000000000a"
NODE_B = "20000000-0000-0000-0000-00000000000b"
CHILD_A = "20000000-0000-0000-0000-0000000000a1"


@dataclass
class _User:
    user_id: str
    tenant_id: str
    warehouse_id: str | None
    region_id: str | None
    role: str


def _grant() -> MagicMock:
    grant = MagicMock()
    grant.grant_type = "FULL"
    return grant


async def _check(user: _User, resource_wh: str):
    with (
        patch(
            "shared.permissions.middleware.get_role_permission",
            new=AsyncMock(return_value=_grant()),
        ),
        patch("shared.permissions.middleware.audit_log", new=AsyncMock()),
    ):
        return await check_permission(
            user,
            PERMISSIONS.INVENTORY_RECEIVE,
            {"tenant_id": TENANT, "warehouse_id": resource_wh},
        )


# ── G1: fail closed for a facility-scoped user with no node ─────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["WM", "SA_GT", "RT", "RM"])
async def test_facility_role_without_node_is_denied(role: str) -> None:
    result = await _check(_User("u", TENANT, None, None, role), NODE_A)
    assert not result.allowed
    assert "warehouse" in result.reason


@pytest.mark.asyncio
async def test_lm_without_node_is_tenant_wide_track_b() -> None:
    """Business rule 25 (LM Track B): an LM with no node sees the tenant."""
    result = await _check(_User("u", TENANT, None, None, "LM"), NODE_A)
    assert result.allowed


# ── G3: RM is limited to its region ─────────────────────────────────────────


def test_rm_is_a_facility_scoped_role() -> None:
    assert "RM" in FACILITY_SCOPED_ROLES
    assert TENANT_WIDE_ROLES == {"TA", "NM", "SA", "AU"}


@pytest.mark.asyncio
async def test_rm_allowed_on_resource_in_own_region() -> None:
    # db is None in check_permission, so scope falls back to the exact node.
    result = await _check(_User("u", TENANT, NODE_A, None, "RM"), NODE_A)
    assert result.allowed


@pytest.mark.asyncio
async def test_rm_denied_on_resource_in_another_region() -> None:
    result = await _check(_User("u", TENANT, NODE_A, None, "RM"), NODE_B)
    assert not result.allowed
    assert "warehouse" in result.reason


# ── resolve_node_scope (read side) ──────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["TA", "NM", "SA", "AU"])
async def test_tenant_wide_roles_resolve_to_none(role: str) -> None:
    user = _User("u", TENANT, NODE_A, None, role)
    assert await resolve_node_scope(MagicMock(), user) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["WM", "LM", "SA_GT", "RT", "RM"])
async def test_facility_role_resolves_to_subtree_lowercased(role: str) -> None:
    fake = AsyncMock(return_value={NODE_A.upper(), CHILD_A})
    with patch("shared.permissions.hierarchy_service.get_descendant_node_ids", new=fake):
        scope = await resolve_node_scope(MagicMock(), _User("u", TENANT, NODE_A, None, role))
    assert scope == {NODE_A.lower(), CHILD_A.lower()}
    fake.assert_awaited_once()


@pytest.mark.asyncio
async def test_facility_role_without_node_resolves_to_empty() -> None:
    assert await resolve_node_scope(MagicMock(), _User("u", TENANT, None, None, "WM")) == set()
