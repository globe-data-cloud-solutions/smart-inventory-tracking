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
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("DATABASE_READ_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

# ── Scoped sys.path: guarantee tenant-service routers win the lookup ──────────
_TENANT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
_was_on_path = _TENANT_ROOT in sys.path
if not _was_on_path:
    sys.path.insert(0, _TENANT_ROOT)
# ─────────────────────────────────────────────────────────────────────────────

from dataclasses import dataclass, field  # noqa: E402 - sys.path/env setup above must run first
from typing import Any  # noqa: E402 - sys.path/env setup above must run first
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402 - sys.path/env setup above must run first
from uuid import UUID, uuid4  # noqa: E402 - sys.path/env setup above must run first

import asyncpg  # noqa: E402 - sys.path/env setup above must run first
import pytest  # noqa: E402 - sys.path/env setup above must run first
from fastapi import HTTPException  # noqa: E402 - sys.path/env setup above must run first
from sqlalchemy.exc import IntegrityError  # noqa: E402 - sys.path/env setup above must run first

TENANT_ID = "aaaaaaaa-0000-0000-0000-000000000001"
NODE_ID = "bbbbbbbb-0000-0000-0000-000000000001"
LEVEL_ID = "cccccccc-0000-0000-0000-000000000001"


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
            res.scalar = MagicMock(return_value=0)
        elif isinstance(r, list):
            res.fetchone = MagicMock(return_value=r[0] if r else None)
            res.fetchall = MagicMock(return_value=r)
            res.scalar = MagicMock(return_value=len(r))
        else:
            res.fetchone = MagicMock(return_value=r)
            res.fetchall = MagicMock(return_value=[r])
            res.scalar = MagicMock(return_value=1)
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
            id=UUID(LEVEL_ID),
            tenant_id=UUID(TENANT_ID),
            level_number=2,
            level_name="Region",
            default_role_code="RM",
            role_display_label="Regional Manager",
            is_stock_holding=False,
            is_active=True,
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
                    HierarchyLevelIn(level_number=1, default_role_code="NM", level_name="Factory"),
                    HierarchyLevelIn(
                        level_number=2, default_role_code="RM", level_name="Factory"
                    ),  # duplicate name
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
                    HierarchyLevelIn(level_number=1, default_role_code="NM", level_name="Factory"),
                    HierarchyLevelIn(
                        level_number=1, default_role_code="NM", level_name="Factory Duplicate"
                    ),
                ],
                user=_Caller(),
                db=db,
            )
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "DUPLICATE_LEVEL_NUMBER"

    async def test_grow_levels_after_initial_save_allowed(self) -> None:
        """G3a (updated): growing from 4 → 5 levels is always permitted.
        The lock only fires when shrinking to a level below the highest
        active node — no exception expected here."""
        from routers.hierarchy import upsert_hierarchy_config, HierarchyLevelIn

        existing_count_res = MagicMock()
        existing_count_res.scalar = MagicMock(return_value=4)
        # Growing path: only the COUNT query fires; INSERT/UPDATE calls follow
        db = AsyncMock()
        db.execute = AsyncMock(return_value=existing_count_res)

        # Should not raise — growing is always safe
        with _GRANT_ALL:
            try:
                await upsert_hierarchy_config(
                    tenant_id=UUID(TENANT_ID),
                    body=[
                        HierarchyLevelIn(
                            level_number=1, default_role_code="NM", level_name="Factory"
                        ),
                        HierarchyLevelIn(
                            level_number=2, default_role_code="RM", level_name="Region"
                        ),
                        HierarchyLevelIn(
                            level_number=3, default_role_code="WM", level_name="Warehouse"
                        ),
                        HierarchyLevelIn(
                            level_number=4, default_role_code="LM", level_name="Satellite"
                        ),
                        HierarchyLevelIn(
                            level_number=5, default_role_code="AU", level_name="Outpost"
                        ),
                    ],
                    user=_Caller(),
                    db=db,
                )
            except HTTPException as exc:
                pytest.fail(f"Growing levels should not raise, got {exc.status_code}: {exc.detail}")

    async def test_same_level_count_after_initial_save_allows_edit(self) -> None:
        """G3a: PUTting the SAME count (4) as already saved is allowed — this is
        how a TA renames/edits existing levels without changing the count."""
        from routers.hierarchy import upsert_hierarchy_config, HierarchyLevelIn

        execute_calls: list[str] = []

        async def _capture(stmt, params=None, **kw) -> MagicMock:
            execute_calls.append(str(stmt))
            res = MagicMock()
            res.scalar = MagicMock(return_value=4)  # existing_count
            res.fetchall = MagicMock(
                return_value=[
                    _row(
                        id=uuid4(),
                        tenant_id=UUID(TENANT_ID),
                        level_number=n,
                        level_name=f"Level {n}",
                        default_role_code=None,
                        role_display_label=None,
                        is_stock_holding=True,
                        is_active=True,
                    )
                    for n in (1, 2, 3, 4)
                ]
            )
            return res

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=_capture)
        db.commit = AsyncMock()

        with _GRANT_ALL:
            result = await upsert_hierarchy_config(
                tenant_id=UUID(TENANT_ID),
                body=[
                    HierarchyLevelIn(
                        level_number=1, default_role_code="NM", level_name="Factory Renamed"
                    ),
                    HierarchyLevelIn(level_number=2, default_role_code="RM", level_name="Region"),
                    HierarchyLevelIn(
                        level_number=3, default_role_code="WM", level_name="Warehouse"
                    ),
                    HierarchyLevelIn(
                        level_number=4, default_role_code="LM", level_name="Satellite"
                    ),
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
                tenant_id=UUID(TENANT_ID),
                user=_Caller(role="SA"),
                db=db,
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
                tenant_id=UUID(TENANT_ID),
                user=_Caller(role="SA"),
                db=db,
            )

        assert result.data["reset"] is True

    async def test_ta_reset_forbidden(self) -> None:
        """G3b: a TA (non-SA caller) is rejected with 403 FORBIDDEN before any DB call,
        even though tenant:manage itself is mocked as granted."""
        from routers.hierarchy import reset_hierarchy_config

        db = _db_seq()  # no DB calls should be needed — role check fires first

        with _GRANT_ALL, pytest.raises(HTTPException) as exc_info:
            await reset_hierarchy_config(
                tenant_id=UUID(TENANT_ID),
                user=_Caller(role="TA"),
                db=db,
            )
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["code"] == "FORBIDDEN"


# ── Test 2: Org node deactivation / reactivation ─────────────────────────────


@pytest.mark.unit
class TestNodeDeactivation:
    async def test_deactivate_node_no_stock(self) -> None:
        """A clean node (no stock, transfers, adjustments, or sole users) deactivates."""
        from routers.hierarchy import deactivate_org_node

        node_row = _row(id=UUID(NODE_ID))
        transfer_row = _row(cnt=0)
        adj_row = _row(cnt=0)
        sole_row = _row(cnt=0)
        stock_row = _row(total=0)
        db = _db_seq(node_row, transfer_row, adj_row, sole_row, stock_row, None)

        with _GRANT_ALL:
            result = await deactivate_org_node(
                tenant_id=UUID(TENANT_ID),
                node_id=UUID(NODE_ID),
                user=_Caller(),
                db=db,
            )

        assert result.data == {"deactivated": NODE_ID}

    async def test_deactivate_blocked_with_stock(self) -> None:
        """A node with stock on hand cannot be deactivated — 422 NODE_HAS_STOCK."""
        from routers.hierarchy import deactivate_org_node

        node_row = _row(id=UUID(NODE_ID))
        stock_row = _row(total=50)
        # Production order: transfer(0) → adj(0) → sole(0) → stock(50 → 422)
        db = _db_seq(node_row, _row(cnt=0), _row(cnt=0), _row(cnt=0), stock_row)

        with _GRANT_ALL, pytest.raises(HTTPException) as exc_info:
            await deactivate_org_node(
                tenant_id=UUID(TENANT_ID),
                node_id=UUID(NODE_ID),
                user=_Caller(),
                db=db,
            )
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "NODE_HAS_STOCK"

    async def test_deactivate_blocked_with_open_transfers(self) -> None:
        """A node with open (non-terminal) transfers cannot be deactivated."""
        from routers.hierarchy import deactivate_org_node

        node_row = _row(id=UUID(NODE_ID))
        transfer_row = _row(cnt=2)
        # Transfer is check #1 — raises 422 immediately, no further DB calls
        db = _db_seq(node_row, transfer_row)

        with _GRANT_ALL, pytest.raises(HTTPException) as exc_info:
            await deactivate_org_node(
                tenant_id=UUID(TENANT_ID),
                node_id=UUID(NODE_ID),
                user=_Caller(),
                db=db,
            )
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "NODE_HAS_OPEN_TRANSFERS"

    async def test_deactivate_blocked_with_pending_adjustments(self) -> None:
        """A node with pending (non-terminal) adjustments cannot be deactivated."""
        from routers.hierarchy import deactivate_org_node

        node_row = _row(id=UUID(NODE_ID))
        transfer_row = _row(cnt=0)
        adj_row = _row(cnt=1)
        # Transfer(0) passes, adj(1) raises 422 immediately
        db = _db_seq(node_row, transfer_row, adj_row)

        with _GRANT_ALL, pytest.raises(HTTPException) as exc_info:
            await deactivate_org_node(
                tenant_id=UUID(TENANT_ID),
                node_id=UUID(NODE_ID),
                user=_Caller(),
                db=db,
            )
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "NODE_HAS_PENDING_ADJUSTMENTS"

    async def test_deactivate_blocked_with_sole_users(self) -> None:
        """A node that is some staff member's only position cannot be deactivated."""
        from routers.hierarchy import deactivate_org_node

        node_row = _row(id=UUID(NODE_ID))
        transfer_row = _row(cnt=0)
        adj_row = _row(cnt=0)
        sole_row = _row(cnt=1)
        # Transfer(0) and adj(0) pass, sole(1) raises 422 immediately
        db = _db_seq(node_row, transfer_row, adj_row, sole_row)

        with _GRANT_ALL, pytest.raises(HTTPException) as exc_info:
            await deactivate_org_node(
                tenant_id=UUID(TENANT_ID),
                node_id=UUID(NODE_ID),
                user=_Caller(),
                db=db,
            )
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "NODE_HAS_SOLE_USERS"

    async def test_reactivate_node(self) -> None:
        """A deactivated approval-only node reactivates with no plan-cap pre-check."""
        from routers.hierarchy import reactivate_org_node

        node_row = _row(id=UUID(NODE_ID), hierarchy_level=1, is_stock_holding=False)
        db = _db_seq(node_row, None)

        with _GRANT_ALL:
            result = await reactivate_org_node(
                tenant_id=UUID(TENANT_ID),
                node_id=UUID(NODE_ID),
                user=_Caller(),
                db=db,
            )

        assert result.data == {"reactivated": NODE_ID}

    async def test_reactivate_stock_holding_node_checks_plan_cap(self) -> None:
        """Reactivating a stock-holding node (any level) runs the plan-cap check."""
        from routers.hierarchy import reactivate_org_node

        node_row = _row(id=UUID(NODE_ID), hierarchy_level=1, is_stock_holding=True)
        db = _db_seq(node_row, None)

        with (
            _GRANT_ALL,
            patch("routers.hierarchy.check_plan_create_warehouse", new=AsyncMock()) as mock_check,
        ):
            result = await reactivate_org_node(
                tenant_id=UUID(TENANT_ID),
                node_id=UUID(NODE_ID),
                user=_Caller(),
                db=db,
            )

        mock_check.assert_awaited_once()
        assert result.data == {"reactivated": NODE_ID}

    async def test_non_ta_cannot_deactivate(self) -> None:
        """A caller without tenant:manage (e.g. WM) is rejected with 403 before any DB access."""
        from routers.hierarchy import deactivate_org_node

        db = _db_seq()  # no DB calls expected — permission check fails first

        with _DENY_ALL, pytest.raises(HTTPException) as exc_info:
            await deactivate_org_node(
                tenant_id=UUID(TENANT_ID),
                node_id=UUID(NODE_ID),
                user=_Caller(role="WM"),
                db=db,
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
                tenant_id=UUID(TENANT_ID),
                include_inactive=False,
                user=_Caller(),
                db=db,
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
                tenant_id=UUID(TENANT_ID),
                include_inactive=True,
                user=_Caller(),
                db=db,
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
            id=UUID(NODE_ID),
            tenant_id=UUID(TENANT_ID),
            name="Region A",
            code="RA",
            hierarchy_level=2,
            parent_node_id=None,
            is_stock_holding=False,
            is_active=True,
            address=None,
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
            id=UUID(NODE_ID),
            tenant_id=UUID(TENANT_ID),
            name="WHA4",
            code="WHA4",
            hierarchy_level=4,
            parent_node_id=None,
            is_stock_holding=False,
            is_active=True,
            address=None,
        )
        level_row = _row(is_stock_holding=True)
        db = _db_seq(
            existing_row, level_row, None, None, None
        )  # existing, level check, UPDATE, _get_level_name, node manager

        with (
            _GRANT_ALL,
            patch("routers.hierarchy.check_plan_create_warehouse", new=AsyncMock()) as mock_check,
        ):
            result = await update_org_node(
                tenant_id=UUID(TENANT_ID),
                node_id=UUID(NODE_ID),
                body=OrgNodeUpdate(is_stock_holding=True),
                user=_Caller(),
                db=db,
            )
        mock_check.assert_awaited_once()
        assert result.data.is_stock_holding is True

    async def test_node_off_blocked_by_open_transfers(self) -> None:
        """PATCH is_stock_holding=false is rejected with NODE_STOCK_ACTIVITY /
        NODE_HAS_OPEN_TRANSFERS when the node has open transfers."""
        from routers.hierarchy import update_org_node, OrgNodeUpdate

        existing_row = _row(
            id=UUID(NODE_ID),
            tenant_id=UUID(TENANT_ID),
            name="WHA4",
            code="WHA4",
            hierarchy_level=4,
            parent_node_id=None,
            is_stock_holding=True,
            is_active=True,
            address=None,
        )
        db = _db_seq(existing_row, _row(cnt=2))

        with _GRANT_ALL, pytest.raises(HTTPException) as exc_info:
            await update_org_node(
                tenant_id=UUID(TENANT_ID),
                node_id=UUID(NODE_ID),
                body=OrgNodeUpdate(is_stock_holding=False),
                user=_Caller(),
                db=db,
            )
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "NODE_STOCK_ACTIVITY"
        assert exc_info.value.detail["reason"] == "NODE_HAS_OPEN_TRANSFERS"

    async def test_node_off_blocked_by_pending_adjustments(self) -> None:
        """PATCH is_stock_holding=false is rejected with NODE_STOCK_ACTIVITY /
        NODE_HAS_PENDING_ADJUSTMENTS when the node has pending adjustments."""
        from routers.hierarchy import update_org_node, OrgNodeUpdate

        existing_row = _row(
            id=UUID(NODE_ID),
            tenant_id=UUID(TENANT_ID),
            name="WHA4",
            code="WHA4",
            hierarchy_level=4,
            parent_node_id=None,
            is_stock_holding=True,
            is_active=True,
            address=None,
        )
        db = _db_seq(existing_row, _row(cnt=0), _row(cnt=1))

        with _GRANT_ALL, pytest.raises(HTTPException) as exc_info:
            await update_org_node(
                tenant_id=UUID(TENANT_ID),
                node_id=UUID(NODE_ID),
                body=OrgNodeUpdate(is_stock_holding=False),
                user=_Caller(),
                db=db,
            )
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "NODE_STOCK_ACTIVITY"
        assert exc_info.value.detail["reason"] == "NODE_HAS_PENDING_ADJUSTMENTS"

    async def test_node_off_blocked_by_stock(self) -> None:
        """PATCH is_stock_holding=false is rejected with NODE_STOCK_ACTIVITY /
        NODE_HAS_STOCK when the node has stock on hand."""
        from routers.hierarchy import update_org_node, OrgNodeUpdate

        existing_row = _row(
            id=UUID(NODE_ID),
            tenant_id=UUID(TENANT_ID),
            name="WHA4",
            code="WHA4",
            hierarchy_level=4,
            parent_node_id=None,
            is_stock_holding=True,
            is_active=True,
            address=None,
        )
        db = _db_seq(existing_row, _row(cnt=0), _row(cnt=0), _row(total=50))

        with _GRANT_ALL, pytest.raises(HTTPException) as exc_info:
            await update_org_node(
                tenant_id=UUID(TENANT_ID),
                node_id=UUID(NODE_ID),
                body=OrgNodeUpdate(is_stock_holding=False),
                user=_Caller(),
                db=db,
            )
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "NODE_STOCK_ACTIVITY"
        assert exc_info.value.detail["reason"] == "NODE_HAS_STOCK"

    async def test_node_off_allowed_when_clean(self) -> None:
        """PATCH is_stock_holding=false succeeds when the node has no open
        transfers, pending adjustments, or stock on hand."""
        from routers.hierarchy import update_org_node, OrgNodeUpdate

        existing_row = _row(
            id=UUID(NODE_ID),
            tenant_id=UUID(TENANT_ID),
            name="WHA4",
            code="WHA4",
            hierarchy_level=4,
            parent_node_id=None,
            is_stock_holding=True,
            is_active=True,
            address=None,
        )
        db = _db_seq(existing_row, _row(cnt=0), _row(cnt=0), _row(total=0), None, None, None)

        with _GRANT_ALL:
            result = await update_org_node(
                tenant_id=UUID(TENANT_ID),
                node_id=UUID(NODE_ID),
                body=OrgNodeUpdate(is_stock_holding=False),
                user=_Caller(),
                db=db,
            )
        assert result.data.is_stock_holding is False


# ── Test 4: Hierarchy level PATCH — is_stock_holding guard ──────────────────


@pytest.mark.unit
class TestHierarchyLevelStockToggle:
    async def test_level_off_blocked_with_stock_nodes(self) -> None:
        """PATCH is_stock_holding=false on a level is rejected with
        LEVEL_HAS_STOCK_NODES when an active node at that level still holds stock."""
        from routers.hierarchy import rename_hierarchy_level, HierarchyLevelRename

        current_row = _row(level_number=3, is_stock_holding=True)
        blocked_node = _row(id=UUID(NODE_ID), name="WH South")
        db = _db_seq(current_row, [blocked_node])

        with _GRANT_ALL, pytest.raises(HTTPException) as exc_info:
            await rename_hierarchy_level(
                tenant_id=UUID(TENANT_ID),
                level_id=UUID(LEVEL_ID),
                body=HierarchyLevelRename(is_stock_holding=False),
                user=_Caller(),
                db=db,
            )
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "LEVEL_HAS_STOCK_NODES"
        assert exc_info.value.detail["nodes"] == [{"id": NODE_ID, "name": "WH South"}]

    async def test_level_off_allowed_with_no_stock_nodes(self) -> None:
        """PATCH is_stock_holding=false succeeds when no active node at that
        level currently holds stock."""
        from routers.hierarchy import rename_hierarchy_level, HierarchyLevelRename

        current_row = _row(level_number=3, is_stock_holding=True)
        updated_row = _row(
            id=UUID(LEVEL_ID),
            tenant_id=UUID(TENANT_ID),
            level_number=3,
            level_name="Warehouse",
            default_role_code=None,
            role_display_label=None,
            is_stock_holding=False,
            is_active=True,
        )
        db = _db_seq(current_row, [], updated_row)

        with _GRANT_ALL:
            result = await rename_hierarchy_level(
                tenant_id=UUID(TENANT_ID),
                level_id=UUID(LEVEL_ID),
                body=HierarchyLevelRename(is_stock_holding=False),
                user=_Caller(),
                db=db,
            )
        assert result.data.is_stock_holding is False

    async def test_level_off_allowed_when_already_approval_only(self) -> None:
        """PATCH is_stock_holding=false on a level that's already approval-only
        skips the node lookup entirely and just saves."""
        from routers.hierarchy import rename_hierarchy_level, HierarchyLevelRename

        current_row = _row(level_number=3, is_stock_holding=False)
        updated_row = _row(
            id=UUID(LEVEL_ID),
            tenant_id=UUID(TENANT_ID),
            level_number=3,
            level_name="Warehouse",
            default_role_code=None,
            role_display_label=None,
            is_stock_holding=False,
            is_active=True,
        )
        db = _db_seq(current_row, updated_row)

        with _GRANT_ALL:
            result = await rename_hierarchy_level(
                tenant_id=UUID(TENANT_ID),
                level_id=UUID(LEVEL_ID),
                body=HierarchyLevelRename(is_stock_holding=False),
                user=_Caller(),
                db=db,
            )
        assert result.data.is_stock_holding is False

    async def test_level_on_always_allowed(self) -> None:
        """PATCH is_stock_holding=true never checks nodes — existing nodes at
        that level are left unchanged, only the level's own flag flips."""
        from routers.hierarchy import rename_hierarchy_level, HierarchyLevelRename

        updated_row = _row(
            id=UUID(LEVEL_ID),
            tenant_id=UUID(TENANT_ID),
            level_number=3,
            level_name="Warehouse",
            default_role_code=None,
            role_display_label=None,
            is_stock_holding=True,
            is_active=True,
        )
        db = _db_seq(updated_row)  # single call — no node lookup for true->true/false->true

        with _GRANT_ALL:
            result = await rename_hierarchy_level(
                tenant_id=UUID(TENANT_ID),
                level_id=UUID(LEVEL_ID),
                body=HierarchyLevelRename(is_stock_holding=True),
                user=_Caller(),
                db=db,
            )
        assert result.data.is_stock_holding is True


# ── Test 5: Hierarchy config PUT — closes the unguarded stock-toggle path ────


@pytest.mark.unit
class TestHierarchyConfigPutStockGuard:
    async def test_put_blocks_level_true_to_false_with_stock_nodes(self) -> None:
        """A full-replace PUT that flips an existing level's is_stock_holding
        true→false is blocked the same way the PATCH guard is, when an active
        stock-holding node still sits at that level."""
        from routers.hierarchy import upsert_hierarchy_config, HierarchyLevelIn

        existing_count_res = MagicMock()
        existing_count_res.scalar = MagicMock(return_value=2)

        existing_levels_res = MagicMock()
        existing_levels_res.fetchall = MagicMock(
            return_value=[
                _row(level_number=1, is_stock_holding=True),
                _row(level_number=2, is_stock_holding=True),
            ]
        )

        blocked_nodes_res = MagicMock()
        blocked_nodes_res.fetchall = MagicMock(
            return_value=[_row(id=UUID(NODE_ID), name="WH North")]
        )

        call_count = 0

        async def _capture(stmt, params=None, **kw) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return existing_count_res
            if call_count == 2:
                return existing_levels_res
            if call_count == 3:
                return blocked_nodes_res
            pytest.fail("unexpected extra db.execute call before the guard raises")

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=_capture)

        with _GRANT_ALL, pytest.raises(HTTPException) as exc_info:
            await upsert_hierarchy_config(
                tenant_id=UUID(TENANT_ID),
                body=[
                    HierarchyLevelIn(
                        level_number=1,
                        default_role_code="NM",
                        level_name="Factory",
                        is_stock_holding=True,
                    ),
                    HierarchyLevelIn(
                        level_number=2,
                        default_role_code="RM",
                        level_name="Warehouse",
                        is_stock_holding=False,
                    ),
                ],
                user=_Caller(),
                db=db,
            )
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "LEVEL_HAS_STOCK_NODES"
        assert exc_info.value.detail["nodes"] == [{"id": NODE_ID, "name": "WH North"}]

    async def test_put_allows_level_true_to_false_without_stock_nodes(self) -> None:
        """Same true→false flip via PUT succeeds when no active node at that
        level currently holds stock."""
        from routers.hierarchy import upsert_hierarchy_config, HierarchyLevelIn

        existing_count_res = MagicMock()
        existing_count_res.scalar = MagicMock(return_value=2)

        existing_levels_res = MagicMock()
        existing_levels_res.fetchall = MagicMock(
            return_value=[
                _row(level_number=1, is_stock_holding=True),
                _row(level_number=2, is_stock_holding=True),
            ]
        )

        blocked_nodes_res = MagicMock()
        blocked_nodes_res.fetchall = MagicMock(return_value=[])

        final_rows_res = MagicMock()
        final_rows_res.fetchall = MagicMock(
            return_value=[
                _row(
                    id=uuid4(),
                    tenant_id=UUID(TENANT_ID),
                    level_number=1,
                    level_name="Factory",
                    default_role_code=None,
                    role_display_label=None,
                    is_stock_holding=True,
                    is_active=True,
                ),
                _row(
                    id=uuid4(),
                    tenant_id=UUID(TENANT_ID),
                    level_number=2,
                    level_name="Warehouse",
                    default_role_code=None,
                    role_display_label=None,
                    is_stock_holding=False,
                    is_active=True,
                ),
            ]
        )

        call_count = 0

        async def _capture(stmt, params=None, **kw) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return existing_count_res
            if call_count == 2:
                return existing_levels_res
            if call_count == 3:
                return blocked_nodes_res
            if call_count in (4, 5, 6):  # two INSERT upserts + deactivate-missing-levels UPDATE
                return MagicMock()
            return final_rows_res

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=_capture)

        with _GRANT_ALL:
            result = await upsert_hierarchy_config(
                tenant_id=UUID(TENANT_ID),
                body=[
                    HierarchyLevelIn(
                        level_number=1,
                        default_role_code="NM",
                        level_name="Factory",
                        is_stock_holding=True,
                    ),
                    HierarchyLevelIn(
                        level_number=2,
                        default_role_code="RM",
                        level_name="Warehouse",
                        is_stock_holding=False,
                    ),
                ],
                user=_Caller(),
                db=db,
            )
        assert len(result.data) == 2
        assert result.data[1].is_stock_holding is False

    async def test_put_new_level_unaffected_by_stock_guard(self) -> None:
        """A brand-new level (not in existing config) is never subject to the
        true→false node guard, regardless of its submitted is_stock_holding."""
        from routers.hierarchy import upsert_hierarchy_config, HierarchyLevelIn

        existing_count_res = MagicMock()
        existing_count_res.scalar = MagicMock(return_value=0)

        call_count = 0

        async def _capture(stmt, params=None, **kw) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return existing_count_res
            return MagicMock()  # INSERT / deactivate-missing-levels / final SELECT

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=_capture)

        with _GRANT_ALL:
            try:
                await upsert_hierarchy_config(
                    tenant_id=UUID(TENANT_ID),
                    body=[
                        HierarchyLevelIn(
                            level_number=1,
                            default_role_code="NM",
                            level_name="Factory",
                            is_stock_holding=False,
                        )
                    ],
                    user=_Caller(),
                    db=db,
                )
            except HTTPException as exc:
                pytest.fail(f"New level should never trigger the stock guard, got {exc.detail}")


# ── Level roles: required on save, locked while nodes exist (Option B) ───────


def _role_db(responses: dict[str, object]) -> AsyncMock:
    """Fake session: the first response whose key appears in the SQL wins."""

    async def _execute(stmt, params=None, **kw):
        sql = str(stmt)
        for key, res in responses.items():
            if key in sql:
                return res
        res = MagicMock()
        res.scalar = MagicMock(return_value=0)
        res.fetchall = MagicMock(return_value=[])
        return res

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=_execute)
    db.commit = AsyncMock()
    return db


def _result(**fields) -> MagicMock:
    res = MagicMock()
    res.fetchone = MagicMock(return_value=_row(**fields))
    res.fetchall = MagicMock(return_value=[_row(**fields)])
    return res


@pytest.mark.unit
class TestLevelRoleRequired:
    async def test_save_without_role_is_rejected(self) -> None:
        from routers.hierarchy import HierarchyLevelIn, upsert_hierarchy_config

        db = _role_db({})
        with _GRANT_ALL, pytest.raises(HTTPException) as exc:
            await upsert_hierarchy_config(
                tenant_id=UUID(TENANT_ID),
                body=[
                    HierarchyLevelIn(level_number=1, level_name="NM level", default_role_code="NM"),
                    HierarchyLevelIn(level_number=2, level_name="Region", default_role_code=None),
                ],
                user=_Caller(),
                db=db,
            )
        assert exc.value.status_code == 422
        assert exc.value.detail["code"] == "LEVEL_ROLE_REQUIRED"
        assert exc.value.detail["level_number"] == 2

    async def test_sa_and_ta_codes_are_not_level_roles(self) -> None:
        from routers.hierarchy import HierarchyLevelIn, upsert_hierarchy_config

        db = _role_db({})
        with _GRANT_ALL, pytest.raises(HTTPException) as exc:
            await upsert_hierarchy_config(
                tenant_id=UUID(TENANT_ID),
                body=[HierarchyLevelIn(level_number=1, level_name="Top", default_role_code="TA")],
                user=_Caller(),
                db=db,
            )
        assert exc.value.detail["code"] == "LEVEL_ROLE_REQUIRED"


@pytest.mark.unit
class TestLevelRoleLockedOnSave:
    async def test_changing_role_with_nodes_at_level_is_locked(self) -> None:
        from routers.hierarchy import HierarchyLevelIn, upsert_hierarchy_config

        db = _role_db(
            {
                "SELECT level_number, default_role_code FROM tenant_hierarchy_config": _saved_roles(
                    {2: "RM"}
                ),
                "AS n FROM organization_node": _count(3),
            }
        )
        with _GRANT_ALL, pytest.raises(HTTPException) as exc:
            await upsert_hierarchy_config(
                tenant_id=UUID(TENANT_ID),
                body=[
                    HierarchyLevelIn(level_number=1, level_name="Top", default_role_code="NM"),
                    HierarchyLevelIn(level_number=2, level_name="Region", default_role_code="LM"),
                ],
                user=_Caller(),
                db=db,
            )
        assert exc.value.status_code == 409
        assert exc.value.detail["code"] == "LEVEL_ROLE_LOCKED"

    async def test_changing_role_without_nodes_is_allowed(self) -> None:
        from routers.hierarchy import HierarchyLevelIn, upsert_hierarchy_config

        db = _role_db(
            {
                "SELECT level_number, default_role_code FROM tenant_hierarchy_config": _saved_roles(
                    {2: "RM"}
                ),
                "AS n FROM organization_node": _count(0),
                "SELECT id, tenant_id, level_number": _rows_for_levels({2: "LM"}),
            }
        )
        with _GRANT_ALL:
            result = await upsert_hierarchy_config(
                tenant_id=UUID(TENANT_ID),
                body=[
                    HierarchyLevelIn(level_number=1, level_name="Top", default_role_code="NM"),
                    HierarchyLevelIn(level_number=2, level_name="Region", default_role_code="LM"),
                ],
                user=_Caller(),
                db=db,
            )
        assert result.data is not None


@pytest.mark.unit
class TestSetLevelRoleEndpoint:
    async def _call(self, db, role: str, level_id: str = LEVEL_ID, caller: _Caller | None = None):
        from routers.hierarchy import HierarchyLevelRoleIn, set_hierarchy_level_role

        with _GRANT_ALL, patch("routers.hierarchy.audit_log", new=AsyncMock()) as audit:
            result = await set_hierarchy_level_role(
                tenant_id=UUID(TENANT_ID),
                level_id=UUID(level_id),
                body=HierarchyLevelRoleIn(default_role_code=role),
                user=caller or _Caller(),
                db=db,
            )
        return result, audit

    async def test_invalid_role_code_rejected(self) -> None:
        db = _role_db({})
        with pytest.raises(HTTPException) as exc:
            await self._call(db, "SA")
        assert exc.value.status_code == 422
        assert exc.value.detail["code"] == "LEVEL_ROLE_INVALID"

    async def test_unknown_level_is_404(self) -> None:
        db = _role_db({"SELECT id, level_number, default_role_code": _none()})
        with pytest.raises(HTTPException) as exc:
            await self._call(db, "WM")
        assert exc.value.status_code == 404

    async def test_unset_role_can_be_repaired_even_with_nodes(self) -> None:
        db = _role_db(
            {
                "SELECT id, level_number, default_role_code": _result(
                    id=UUID(LEVEL_ID), level_number=3, default_role_code=None
                ),
                "AS n FROM organization_node": _count(2),
                "SELECT id, tenant_id, level_number": _result(
                    id=UUID(LEVEL_ID),
                    tenant_id=UUID(TENANT_ID),
                    level_number=3,
                    level_name="Warehouse",
                    default_role_code="WM",
                    role_display_label=None,
                    is_stock_holding=True,
                    is_active=True,
                ),
            }
        )
        result, audit = await self._call(db, "WM")
        assert result.data.default_role_code == "WM"
        assert result.data.active_node_count == 2
        audit.assert_awaited_once()

    async def test_changing_role_with_nodes_is_locked(self) -> None:
        db = _role_db(
            {
                "SELECT id, level_number, default_role_code": _result(
                    id=UUID(LEVEL_ID), level_number=3, default_role_code="WM"
                ),
                "AS n FROM organization_node": _count(1),
            }
        )
        with pytest.raises(HTTPException) as exc:
            await self._call(db, "LM")
        assert exc.value.status_code == 409
        assert exc.value.detail["code"] == "LEVEL_ROLE_LOCKED"

    async def test_changing_role_after_nodes_removed_is_allowed(self) -> None:
        db = _role_db(
            {
                "SELECT id, level_number, default_role_code": _result(
                    id=UUID(LEVEL_ID), level_number=3, default_role_code="WM"
                ),
                "AS n FROM organization_node": _count(0),
                "SELECT id, tenant_id, level_number": _result(
                    id=UUID(LEVEL_ID),
                    tenant_id=UUID(TENANT_ID),
                    level_number=3,
                    level_name="Warehouse",
                    default_role_code="LM",
                    role_display_label=None,
                    is_stock_holding=True,
                    is_active=True,
                ),
            }
        )
        result, audit = await self._call(db, "LM")
        assert result.data.default_role_code == "LM"
        audit.assert_awaited_once()

    async def test_same_role_is_a_no_op(self) -> None:
        db = _role_db(
            {
                "SELECT id, level_number, default_role_code": _result(
                    id=UUID(LEVEL_ID), level_number=3, default_role_code="WM"
                ),
                "AS n FROM organization_node": _count(4),
                "SELECT id, tenant_id, level_number": _result(
                    id=UUID(LEVEL_ID),
                    tenant_id=UUID(TENANT_ID),
                    level_number=3,
                    level_name="Warehouse",
                    default_role_code="WM",
                    role_display_label=None,
                    is_stock_holding=True,
                    is_active=True,
                ),
            }
        )
        result, audit = await self._call(db, "WM")
        assert result.data.default_role_code == "WM"
        audit.assert_not_awaited()


def _count(n: int) -> MagicMock:
    res = MagicMock()
    res.fetchone = MagicMock(return_value=SimpleNamespace(n=n))
    return res


def _none() -> MagicMock:
    res = MagicMock()
    res.fetchone = MagicMock(return_value=None)
    return res


def _saved_roles(roles: dict[int, str]) -> MagicMock:
    res = MagicMock()
    res.fetchall = MagicMock(
        return_value=[
            SimpleNamespace(level_number=n, default_role_code=r) for n, r in roles.items()
        ]
    )
    return res


def _rows_for_levels(roles: dict[int, str]) -> MagicMock:
    res = MagicMock()
    res.fetchall = MagicMock(
        return_value=[
            _row(
                id=uuid4(),
                tenant_id=UUID(TENANT_ID),
                level_number=n,
                level_name=f"Level {n}",
                default_role_code=r,
                role_display_label=None,
                is_stock_holding=True,
                is_active=True,
            )
            for n, r in roles.items()
        ]
    )
    return res


@pytest.mark.unit
class TestSaOverridesLockedRole:
    async def test_sa_may_change_locked_role_and_it_is_audited(self) -> None:
        from routers.hierarchy import HierarchyLevelRoleIn, set_hierarchy_level_role

        db = _role_db(
            {
                "SELECT id, level_number, default_role_code": _result(
                    id=UUID(LEVEL_ID), level_number=3, default_role_code="WM"
                ),
                "AS n FROM organization_node": _count(5),
                "SELECT id, tenant_id, level_number": _result(
                    id=UUID(LEVEL_ID),
                    tenant_id=UUID(TENANT_ID),
                    level_number=3,
                    level_name="Warehouse",
                    default_role_code="LM",
                    role_display_label=None,
                    is_stock_holding=True,
                    is_active=True,
                ),
            }
        )
        with _GRANT_ALL, patch("routers.hierarchy.audit_log", new=AsyncMock()) as audit:
            result = await set_hierarchy_level_role(
                tenant_id=UUID(TENANT_ID),
                level_id=UUID(LEVEL_ID),
                body=HierarchyLevelRoleIn(default_role_code="LM"),
                user=_Caller(role="SA"),
                db=db,
            )
        assert result.data.default_role_code == "LM"
        audit.assert_awaited_once()
        assert audit.await_args.args[2]["override"] is True
        assert audit.await_args.args[2]["active_node_count"] == 5

    async def test_ta_still_locked_out(self) -> None:
        from routers.hierarchy import HierarchyLevelRoleIn, set_hierarchy_level_role

        db = _role_db(
            {
                "SELECT id, level_number, default_role_code": _result(
                    id=UUID(LEVEL_ID), level_number=3, default_role_code="WM"
                ),
                "AS n FROM organization_node": _count(5),
            }
        )
        with _GRANT_ALL, pytest.raises(HTTPException) as exc:
            await set_hierarchy_level_role(
                tenant_id=UUID(TENANT_ID),
                level_id=UUID(LEVEL_ID),
                body=HierarchyLevelRoleIn(default_role_code="LM"),
                user=_Caller(role="TA"),
                db=db,
            )
        assert exc.value.detail["code"] == "LEVEL_ROLE_LOCKED"

    async def test_sa_whole_list_save_overrides_and_audits(self) -> None:
        from routers.hierarchy import HierarchyLevelIn, upsert_hierarchy_config

        db = _role_db(
            {
                "SELECT level_number, default_role_code FROM tenant_hierarchy_config": _saved_roles(
                    {2: "RM"}
                ),
                "AS n FROM organization_node": _count(3),
                "SELECT id, tenant_id, level_number": _rows_for_levels({2: "LM"}),
            }
        )
        with _GRANT_ALL, patch("routers.hierarchy.audit_log", new=AsyncMock()) as audit:
            await upsert_hierarchy_config(
                tenant_id=UUID(TENANT_ID),
                body=[
                    HierarchyLevelIn(level_number=1, level_name="Top", default_role_code="NM"),
                    HierarchyLevelIn(level_number=2, level_name="Region", default_role_code="LM"),
                ],
                user=_Caller(role="SA"),
                db=db,
            )
        audit.assert_awaited_once()
        assert audit.await_args.args[2]["override"] is True
