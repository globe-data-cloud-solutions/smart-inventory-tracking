"""Unit tests for hierarchy level rename and org node deactivation/reactivation.

Tests:
1. TestHierarchyLevelRename — PATCH /hierarchy/config/{level_id} (rename-only)
2. TestNodeDeactivation     — PATCH /nodes/{id}/deactivate, /reactivate, GET /nodes filtering

DATABASE_URL and JWT_SECRET must be set before any router import.

sys.path note
─────────────
When the full backend test suite runs, inventory-service's conftest imports
`from main import app`, registering inventory-service/routers in sys.modules.
Any subsequent `from routers.X import ...` then resolves to the wrong package.

Fix mirrors the auth-service pattern: temporarily insert tenant-service root at
position 0, flush stale routers.* entries, then restore sys.path after loading.
Inline imports inside test methods re-resolve after each per-test flush in conftest.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("DATABASE_URL",      "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("DATABASE_READ_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("JWT_SECRET",        "test-secret")
os.environ.setdefault("JWT_SECRET_KEY",    "test-secret")

# ── Scoped sys.path: guarantee tenant-service routers win the lookup ──────────
_TENANT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
_was_on_path = _TENANT_ROOT in sys.path
if not _was_on_path:
    sys.path.insert(0, _TENANT_ROOT)
# ─────────────────────────────────────────────────────────────────────────────

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import asyncpg
import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

TENANT_ID = "aaaaaaaa-0000-0000-0000-000000000001"
NODE_ID   = "bbbbbbbb-0000-0000-0000-000000000001"
LEVEL_ID  = "cccccccc-0000-0000-0000-000000000001"


@dataclass
class _Caller:
    role: str = "TA"
    tenant_id: str = TENANT_ID
    user_id: str = "caller-001"
    warehouse_id: str | None = None
    positions: list[dict[str, Any]] = field(default_factory=list)


def _row(**kwargs: Any) -> MagicMock:
    r = MagicMock()
    for k, v in kwargs.items():
        setattr(r, k, v)
    return r


def _db_seq(*returns: Any) -> AsyncMock:
    """DB mock: each call to execute() returns the next item in `returns`.

    Each item in returns is interpreted as:
      - None      → fetchone=None, fetchall=[], scalar=0
      - MagicMock → fetchone=item, fetchall=[item], scalar=1
      - list      → fetchall=list, fetchone=list[0] (or None if empty)
    """
    db = AsyncMock()
    db.commit = AsyncMock()
    results: list[MagicMock] = []
    for r in returns:
        res = MagicMock()
        if r is None:
            res.fetchone = MagicMock(return_value=None)
            res.fetchall = MagicMock(return_value=[])
            res.scalar   = MagicMock(return_value=0)
        elif isinstance(r, list):
            res.fetchone = MagicMock(return_value=r[0] if r else None)
            res.fetchall = MagicMock(return_value=r)
            res.scalar   = MagicMock(return_value=len(r))
        else:
            res.fetchone = MagicMock(return_value=r)
            res.fetchall = MagicMock(return_value=[r])
            res.scalar   = MagicMock(return_value=1)
        results.append(res)

    db.execute = AsyncMock(side_effect=results)
    return db


# Patch check_permission to always grant/deny — lets unit tests focus on logic, not RBAC.
_GRANT_ALL = patch(
    "shared.permissions.middleware.check_permission",
    new=AsyncMock(return_value=MagicMock(allowed=True, condition=None)),
)
_DENY_ALL = patch(
    "shared.permissions.middleware.check_permission",
    new=AsyncMock(return_value=MagicMock(allowed=False, reason="RBAC_DENIED")),
)


def _unique_violation(constraint_name: str) -> IntegrityError:
    """Build a sqlalchemy IntegrityError wrapping an asyncpg UniqueViolationError,
    matching what asyncpg+SQLAlchemy actually raise on a constraint violation."""
    orig = asyncpg.exceptions.UniqueViolationError("duplicate key value")
    orig.constraint_name = constraint_name
    return IntegrityError("INSERT/UPDATE", {}, orig)


def _db_seq_raising(*returns: Any, raises: Exception) -> AsyncMock:
    """Like _db_seq, but the call AFTER the given `returns` raises `raises` instead
    of returning a result — simulates a DB constraint violation on the statement
    itself rather than on a preceding lookup."""
    db = _db_seq(*returns)
    prior_effects = list(db.execute.side_effect)
    db.execute = AsyncMock(side_effect=prior_effects + [raises])
    return db


# ── Test 1: Hierarchy level rename ───────────────────────────────────────────

@pytest.mark.unit
class TestHierarchyLevelRename:

    async def test_ta_can_rename_level(self) -> None:
        """TA renames a level — PATCH returns 200 with the updated level_name."""
        from routers.hierarchy import rename_hierarchy_level, HierarchyLevelRename

        updated_row = _row(
            id=UUID(LEVEL_ID), tenant_id=UUID(TENANT_ID), level_number=2,
            level_name="Region", default_role_code="RM",
            role_display_label="Regional Manager", is_stock_holding=False, is_active=True,
        )
        db = _db_seq(updated_row)

        with _GRANT_ALL:
            result = await rename_hierarchy_level(
                tenant_id=UUID(TENANT_ID),
                level_id=UUID(LEVEL_ID),
                body=HierarchyLevelRename(level_name="Region"),
                user=_Caller(),
                db=db,
            )

        assert result.data.level_name == "Region"
        assert result.data.id == UUID(LEVEL_ID)
        # level_number, default_role_code, is_stock_holding are untouched by rename
        assert result.data.level_number == 2
        assert result.data.default_role_code == "RM"
        assert result.data.is_stock_holding is False

    def test_rename_validates_min_length(self) -> None:
        """level_name shorter than 2 chars raises ValidationError (→ 422 at the API layer)."""
        from pydantic import ValidationError
        from routers.hierarchy import HierarchyLevelRename

        with pytest.raises(ValidationError):
            HierarchyLevelRename(level_name="X")

    def test_rename_validates_max_length(self) -> None:
        """level_name longer than 50 chars raises ValidationError (→ 422 at the API layer)."""
        from pydantic import ValidationError
        from routers.hierarchy import HierarchyLevelRename

        with pytest.raises(ValidationError):
            HierarchyLevelRename(level_name="A" * 51)

    async def test_non_ta_cannot_rename_level(self) -> None:
        """A caller without tenant:manage (e.g. WM) is rejected with 403 before any DB access."""
        from routers.hierarchy import rename_hierarchy_level, HierarchyLevelRename

        db = _db_seq()  # no DB calls expected — permission check fails first

        with _DENY_ALL, pytest.raises(HTTPException) as exc_info:
            await rename_hierarchy_level(
                tenant_id=UUID(TENANT_ID),
                level_id=UUID(LEVEL_ID),
                body=HierarchyLevelRename(level_name="Region"),
                user=_Caller(role="WM"),
                db=db,
            )
        assert exc_info.value.status_code == 403


# ── Test 1b: Hierarchy config PUT — G1/G2/G3a validation gaps ───────────────

@pytest.mark.unit
class TestHierarchyConfigUpsert:

    async def test_duplicate_level_name_returns_422(self) -> None:
        """G1: PUT /hierarchy/config converts the uq_hierarchy_config_tenant_name
        IntegrityError into a clean 422 DUPLICATE_LEVEL_NAME instead of a raw 500."""
        from routers.hierarchy import upsert_hierarchy_config, HierarchyLevelIn

        # Call sequence: existing_count query (scalar=0), INSERT level 1
        # (succeeds), INSERT level 2 (raises the unique-name violation).
        call_count = 0

        async def _capture(stmt, params=None, **kw) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                res = MagicMock()
                res.scalar = MagicMock(return_value=0)
                return res
            if call_count == 2:
                return MagicMock()
            raise _unique_violation("uq_hierarchy_config_tenant_name")

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=_capture)
        db.commit = AsyncMock()

        with _GRANT_ALL, pytest.raises(HTTPException) as exc_info:
            await upsert_hierarchy_config(
                tenant_id=UUID(TENANT_ID),
                body=[
                    HierarchyLevelIn(level_number=1, level_name="Factory"),
                    HierarchyLevelIn(level_number=2, level_name="Factory"),  # duplicate name
                ],
                user=_Caller(),
                db=db,
            )
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "DUPLICATE_LEVEL_NAME"

    async def test_duplicate_level_number_in_payload_returns_422(self) -> None:
        """G2: two items with the same level_number in one PUT payload are rejected
        before any DB call, instead of silently upserting twice (last write wins)."""
        from routers.hierarchy import upsert_hierarchy_config, HierarchyLevelIn

        db = _db_seq()  # no DB calls should be needed — validation fires first

        with _GRANT_ALL, pytest.raises(HTTPException) as exc_info:
            await upsert_hierarchy_config(
                tenant_id=UUID(TENANT_ID),
                body=[
                    HierarchyLevelIn(level_number=1, level_name="Factory"),
                    HierarchyLevelIn(level_number=1, level_name="Factory Duplicate"),
                ],
                user=_Caller(),
                db=db,
            )
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "DUPLICATE_LEVEL_NUMBER"

    async def test_level_count_change_after_initial_save_locked(self) -> None:
        """G3a: once 4 levels are saved, PUTting 5 is rejected — the level count
        is locked until an SA resets it via the dedicated reset endpoint."""
        from routers.hierarchy import upsert_hierarchy_config, HierarchyLevelIn

        existing_count_res = MagicMock()
        existing_count_res.scalar = MagicMock(return_value=4)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=existing_count_res)  # only 1 call expected

        with _GRANT_ALL, pytest.raises(HTTPException) as exc_info:
            await upsert_hierarchy_config(
                tenant_id=UUID(TENANT_ID),
                body=[
                    HierarchyLevelIn(level_number=1, level_name="Factory"),
                    HierarchyLevelIn(level_number=2, level_name="Region"),
                    HierarchyLevelIn(level_number=3, level_name="Warehouse"),
                    HierarchyLevelIn(level_number=4, level_name="Satellite"),
                    HierarchyLevelIn(level_number=5, level_name="Outpost"),
                ],
                user=_Caller(),
                db=db,
            )
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "LEVEL_COUNT_LOCKED"

    async def test_same_level_count_after_initial_save_allows_edit(self) -> None:
        """G3a: PUTting the SAME count (4) as already saved is allowed — this is
        how a TA renames/edits existing levels without changing the count."""
        from routers.hierarchy import upsert_hierarchy_config, HierarchyLevelIn

        execute_calls: list[str] = []

        async def _capture(stmt, params=None, **kw) -> MagicMock:
            execute_calls.append(str(stmt))
            res = MagicMock()
            res.scalar = MagicMock(return_value=4)  # existing_count
            res.fetchall = MagicMock(return_value=[
                _row(id=uuid4(), tenant_id=UUID(TENANT_ID), level_number=n,
                     level_name=f"Level {n}", default_role_code=None,
                     role_display_label=None, is_stock_holding=True, is_active=True)
                for n in (1, 2, 3, 4)
            ])
            return res

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=_capture)
        db.commit = AsyncMock()

        with _GRANT_ALL:
            result = await upsert_hierarchy_config(
                tenant_id=UUID(TENANT_ID),
                body=[
                    HierarchyLevelIn(level_number=1, level_name="Factory Renamed"),
                    HierarchyLevelIn(level_number=2, level_name="Region"),
                    HierarchyLevelIn(level_number=3, level_name="Warehouse"),
                    HierarchyLevelIn(level_number=4, level_name="Satellite"),
                ],
                user=_Caller(),
                db=db,
            )

        assert len(result.data) == 4
        assert any("INSERT" in s for s in execute_calls)


# ── Test 1c: SA org level reset endpoint — G3b ───────────────────────────────

@pytest.mark.unit
class TestHierarchyConfigReset:

    async def test_sa_reset_blocked_when_nodes_exist(self) -> None:
        """G3b: SA cannot reset hierarchy config while active org nodes exist."""
        from routers.hierarchy import reset_hierarchy_config

        node_count_res = MagicMock()
        node_count_res.scalar = MagicMock(return_value=3)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=node_count_res)  # only 1 call expected

        with _GRANT_ALL, pytest.raises(HTTPException) as exc_info:
            await reset_hierarchy_config(
                tenant_id=UUID(TENANT_ID), user=_Caller(role="SA"), db=db,
            )
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "ORG_NODES_EXIST"

    async def test_sa_reset_succeeds_when_no_nodes(self, monkeypatch: Any) -> None:
        """G3b: SA reset clears the config and returns reset=true when no org
        nodes exist for the tenant."""
        from routers.hierarchy import reset_hierarchy_config

        monkeypatch.setattr("routers.hierarchy.audit_log", AsyncMock())

        node_count_res = MagicMock()
        node_count_res.scalar = MagicMock(return_value=0)
        db = AsyncMock()
        # 2 calls happen (node_count query, then DELETE) — DELETE's return value
        # is never read, so reusing the same mock for both calls is safe.
        db.execute = AsyncMock(return_value=node_count_res)
        db.commit = AsyncMock()

        with _GRANT_ALL:
            result = await reset_hierarchy_config(
                tenant_id=UUID(TENANT_ID), user=_Caller(role="SA"), db=db,
            )

        assert result.data["reset"] is True

    async def test_ta_reset_forbidden(self) -> None:
        """G3b: a TA (non-SA caller) is rejected with 403 FORBIDDEN before any DB call,
        even though tenant:manage itself is mocked as granted."""
        from routers.hierarchy import reset_hierarchy_config

        db = _db_seq()  # no DB calls should be needed — role check fires first

        with _GRANT_ALL, pytest.raises(HTTPException) as exc_info:
            await reset_hierarchy_config(
                tenant_id=UUID(TENANT_ID), user=_Caller(role="TA"), db=db,
            )
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["code"] == "FORBIDDEN"


# ── Test 2: Org node deactivation / reactivation ─────────────────────────────

@pytest.mark.unit
class TestNodeDeactivation:

    async def test_deactivate_node_no_stock(self) -> None:
        """A clean node (no stock, transfers, adjustments, or sole users) deactivates."""
        from routers.hierarchy import deactivate_org_node

        node_row     = _row(id=UUID(NODE_ID))
        stock_row    = _row(total=0)
        transfer_row = _row(cnt=0)
        adj_row      = _row(cnt=0)
        sole_row     = _row(cnt=0)
        db = _db_seq(node_row, stock_row, transfer_row, adj_row, sole_row, None)

        with _GRANT_ALL:
            result = await deactivate_org_node(
                tenant_id=UUID(TENANT_ID), node_id=UUID(NODE_ID), user=_Caller(), db=db,
            )

        assert result.data == {"deactivated": NODE_ID}

    async def test_deactivate_blocked_with_stock(self) -> None:
        """A node with stock on hand cannot be deactivated — 422 NODE_HAS_STOCK."""
        from routers.hierarchy import deactivate_org_node

        node_row  = _row(id=UUID(NODE_ID))
        stock_row = _row(total=50)
        db = _db_seq(node_row, stock_row)

        with _GRANT_ALL, pytest.raises(HTTPException) as exc_info:
            await deactivate_org_node(
                tenant_id=UUID(TENANT_ID), node_id=UUID(NODE_ID), user=_Caller(), db=db,
            )
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "NODE_HAS_STOCK"

    async def test_deactivate_blocked_with_open_transfers(self) -> None:
        """A node with open (non-terminal) transfers cannot be deactivated."""
        from routers.hierarchy import deactivate_org_node

        node_row     = _row(id=UUID(NODE_ID))
        stock_row    = _row(total=0)
        transfer_row = _row(cnt=2)
        db = _db_seq(node_row, stock_row, transfer_row)

        with _GRANT_ALL, pytest.raises(HTTPException) as exc_info:
            await deactivate_org_node(
                tenant_id=UUID(TENANT_ID), node_id=UUID(NODE_ID), user=_Caller(), db=db,
            )
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "NODE_HAS_OPEN_TRANSFERS"

    async def test_deactivate_blocked_with_pending_adjustments(self) -> None:
        """A node with pending (non-terminal) adjustments cannot be deactivated."""
        from routers.hierarchy import deactivate_org_node

        node_row     = _row(id=UUID(NODE_ID))
        stock_row    = _row(total=0)
        transfer_row = _row(cnt=0)
        adj_row      = _row(cnt=1)
        db = _db_seq(node_row, stock_row, transfer_row, adj_row)

        with _GRANT_ALL, pytest.raises(HTTPException) as exc_info:
            await deactivate_org_node(
                tenant_id=UUID(TENANT_ID), node_id=UUID(NODE_ID), user=_Caller(), db=db,
            )
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "NODE_HAS_PENDING_ADJUSTMENTS"

    async def test_deactivate_blocked_with_sole_users(self) -> None:
        """A node that is some staff member's only position cannot be deactivated."""
        from routers.hierarchy import deactivate_org_node

        node_row     = _row(id=UUID(NODE_ID))
        stock_row    = _row(total=0)
        transfer_row = _row(cnt=0)
        adj_row      = _row(cnt=0)
        sole_row     = _row(cnt=1)
        db = _db_seq(node_row, stock_row, transfer_row, adj_row, sole_row)

        with _GRANT_ALL, pytest.raises(HTTPException) as exc_info:
            await deactivate_org_node(
                tenant_id=UUID(TENANT_ID), node_id=UUID(NODE_ID), user=_Caller(), db=db,
            )
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "NODE_HAS_SOLE_USERS"

    async def test_reactivate_node(self) -> None:
        """A deactivated node can be reactivated with no pre-checks."""
        from routers.hierarchy import reactivate_org_node

        node_row = _row(id=UUID(NODE_ID))
        db = _db_seq(node_row, None)

        with _GRANT_ALL:
            result = await reactivate_org_node(
                tenant_id=UUID(TENANT_ID), node_id=UUID(NODE_ID), user=_Caller(), db=db,
            )

        assert result.data == {"reactivated": NODE_ID}

    async def test_non_ta_cannot_deactivate(self) -> None:
        """A caller without tenant:manage (e.g. WM) is rejected with 403 before any DB access."""
        from routers.hierarchy import deactivate_org_node

        db = _db_seq()  # no DB calls expected — permission check fails first

        with _DENY_ALL, pytest.raises(HTTPException) as exc_info:
            await deactivate_org_node(
                tenant_id=UUID(TENANT_ID), node_id=UUID(NODE_ID), user=_Caller(role="WM"), db=db,
            )
        assert exc_info.value.status_code == 403

    async def test_inactive_nodes_excluded_from_default_list(self) -> None:
        """GET /nodes without include_inactive filters is_active = true into the query."""
        from routers.hierarchy import list_org_nodes

        captured_sql: list[str] = []

        async def fake_execute(query: Any, params: Any = None) -> MagicMock:
            captured_sql.append(str(query))
            res = MagicMock()
            res.fetchall = MagicMock(return_value=[])
            res.fetchone = MagicMock(return_value=None)
            return res

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)

        with _GRANT_ALL:
            await list_org_nodes(
                tenant_id=UUID(TENANT_ID), include_inactive=False, user=_Caller(), db=db,
            )

        assert "n.is_active = true" in captured_sql[0]

    async def test_inactive_nodes_included_with_param(self) -> None:
        """GET /nodes?include_inactive=true omits the is_active filter from the query."""
        from routers.hierarchy import list_org_nodes

        captured_sql: list[str] = []

        async def fake_execute(query: Any, params: Any = None) -> MagicMock:
            captured_sql.append(str(query))
            res = MagicMock()
            res.fetchall = MagicMock(return_value=[])
            res.fetchone = MagicMock(return_value=None)
            return res

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)

        with _GRANT_ALL:
            await list_org_nodes(
                tenant_id=UUID(TENANT_ID), include_inactive=True, user=_Caller(), db=db,
            )

        assert "n.is_active = true" not in captured_sql[0]


# ── Test 3: Org node update — is_stock_holding vs level config ──────────────

@pytest.mark.unit
class TestOrgNodeUpdate:

    async def test_cannot_set_stock_holding_on_non_stock_level(self) -> None:
        """PATCH /nodes/{id} with is_stock_holding=true is rejected when the node's
        hierarchy level is configured as non-stock-holding in tenant_hierarchy_config."""
        from routers.hierarchy import update_org_node, OrgNodeUpdate

        existing_row = _row(
            id=UUID(NODE_ID), tenant_id=UUID(TENANT_ID), name="Region A", code="RA",
            hierarchy_level=2, parent_node_id=None, is_stock_holding=False,
            is_active=True, address=None,
        )
        level_row = _row(is_stock_holding=False)
        db = _db_seq(existing_row, level_row)

        with _GRANT_ALL, pytest.raises(HTTPException) as exc_info:
            await update_org_node(
                tenant_id=UUID(TENANT_ID),
                node_id=UUID(NODE_ID),
                body=OrgNodeUpdate(is_stock_holding=True),
                user=_Caller(),
                db=db,
            )
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "LEVEL_DOES_NOT_HOLD_STOCK"

    async def test_can_set_stock_holding_on_stock_level(self) -> None:
        """The same PATCH succeeds when the level IS configured as stock-holding."""
        from routers.hierarchy import update_org_node, OrgNodeUpdate

        existing_row = _row(
            id=UUID(NODE_ID), tenant_id=UUID(TENANT_ID), name="WHA4", code="WHA4",
            hierarchy_level=4, parent_node_id=None, is_stock_holding=False,
            is_active=True, address=None,
        )
        level_row = _row(is_stock_holding=True)
        db = _db_seq(existing_row, level_row, None, None)  # existing, level check, UPDATE, _get_level_name

        with _GRANT_ALL:
            result = await update_org_node(
                tenant_id=UUID(TENANT_ID),
                node_id=UUID(NODE_ID),
                body=OrgNodeUpdate(is_stock_holding=True),
                user=_Caller(),
                db=db,
            )
        assert result.data.is_stock_holding is True
