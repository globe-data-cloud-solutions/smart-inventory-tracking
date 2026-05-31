"""Unit tests for positions, personnel_v2, and transfer_types endpoints.

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

import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

TENANT_ID   = "aaaaaaaa-0000-0000-0000-000000000001"
NODE_ID     = "bbbbbbbb-0000-0000-0000-000000000001"
POSITION_ID = "cccccccc-0000-0000-0000-000000000001"
USER_ID     = "dddddddd-0000-0000-0000-000000000001"
CONFIG_ID   = "eeeeeeee-0000-0000-0000-000000000001"


@dataclass
class _Caller:
    role: str = "SA"
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
      - None  → fetchone=None, fetchall=[], scalar=0
      - int   → scalar=int, fetchone=MagicMock, fetchall=[]
      - MagicMock → fetchone=item, fetchall=[item], scalar=1
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
        elif isinstance(r, int):
            res.fetchone = MagicMock(return_value=_row(count=r) if r else None)
            res.fetchall = MagicMock(return_value=[])
            res.scalar   = MagicMock(return_value=r)
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


# Patch check_permission to always grant access — lets unit tests focus on logic, not RBAC.
_GRANT_ALL = patch(
    "shared.permissions.middleware.check_permission",
    new=AsyncMock(return_value=MagicMock(allowed=True, condition=None)),
)


# ── Test 1 & 2: Position creation ────────────────────────────────────────────

@pytest.mark.unit
class TestPositionCreate:

    async def test_position_create_at_node(self) -> None:
        """POST /nodes/{node_id}/positions succeeds for a valid role_code (WM)."""
        from routers.positions import create_position, PositionCreate

        node_row = _row(id=NODE_ID)
        db = _db_seq(node_row, None)  # node found, no reports_to lookup needed

        with _GRANT_ALL:
            result = await create_position(
                tenant_id=UUID(TENANT_ID),
                node_id=UUID(NODE_ID),
                body=PositionCreate(title="WH Manager North", role_code="WM"),
                user=_Caller(),
                db=db,
            )

        assert result.data.title     == "WH Manager North"
        assert result.data.role_code == "WM"
        assert result.data.is_active is True

    async def test_position_sa_ta_role_blocked(self) -> None:
        """POST /positions raises 422 when role_code is SA or TA (not facility-level roles)."""
        from routers.positions import create_position, PositionCreate, ALLOWED_POSITION_ROLE_CODES

        assert "SA" not in ALLOWED_POSITION_ROLE_CODES
        assert "TA" not in ALLOWED_POSITION_ROLE_CODES

        for blocked in ("SA", "TA"):
            db = _db_seq()  # no DB calls should be needed
            with _GRANT_ALL, pytest.raises(HTTPException) as exc_info:
                await create_position(
                    tenant_id=UUID(TENANT_ID),
                    node_id=UUID(NODE_ID),
                    body=PositionCreate(title=f"{blocked} role", role_code=blocked),
                    user=_Caller(),
                    db=db,
                )
            assert exc_info.value.status_code == 422
            assert exc_info.value.detail["code"] == "INVALID_ROLE_CODE"

    async def test_position_delete_blocked_active_personnel(self) -> None:
        """DELETE /positions/{id} raises 422 when personnel are actively assigned."""
        from routers.positions import delete_position

        pos_row = _row(id=POSITION_ID)
        db = _db_seq(pos_row, 2)  # position found, 2 active personnel

        with _GRANT_ALL, pytest.raises(HTTPException) as exc_info:
            await delete_position(
                tenant_id=UUID(TENANT_ID),
                position_id=UUID(POSITION_ID),
                user=_Caller(),
                db=db,
            )
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "POSITION_HAS_ACTIVE_PERSONNEL"


# ── Test 3: Personnel v2 ─────────────────────────────────────────────────────

@pytest.mark.unit
class TestPersonnelV2:

    async def test_personnel_create_with_position(self) -> None:
        """POST /users creates user + PRIMARY personnel_position when position_id provided."""
        from routers.personnel_v2 import create_user, UserCreate

        pos_row = _row(id=POSITION_ID, title="Main WH Manager", role_code="WM",
                       node_id=NODE_ID, node_name="Main WH", hierarchy_level=1)

        db = _db_seq(
            None,     # no duplicate email
            None,     # INSERT users
            pos_row,  # position lookup
            None,     # INSERT personnel_positions
        )

        with _GRANT_ALL:
            result = await create_user(
                tenant_id=UUID(TENANT_ID),
                body=UserCreate(
                    name="Abebe Bekele",
                    email="abebe@test.com",
                    password="TestPass@2026",
                    position_id=UUID(POSITION_ID),
                ),
                user=_Caller(),
                db=db,
            )

        assert result.data.email == "abebe@test.com"
        assert result.data.must_reset_password is True
        assert result.data.primary_position is not None
        assert result.data.primary_position.role_code == "WM"
        assert result.data.primary_position.assignment_type == "PRIMARY"

    async def test_personnel_assign_duplicate_primary_rejected(self) -> None:
        """POST /users/{id}/positions rejects a second PRIMARY assignment."""
        from routers.personnel_v2 import assign_position, AssignPositionRequest

        user_row   = _row(id=USER_ID)
        existing   = _row(id=str(uuid4()))  # existing PRIMARY

        db = _db_seq(user_row, existing)

        with _GRANT_ALL, pytest.raises(HTTPException) as exc_info:
            await assign_position(
                tenant_id=UUID(TENANT_ID),
                user_id=UUID(USER_ID),
                body=AssignPositionRequest(
                    position_id=UUID(POSITION_ID),
                    assignment_type="PRIMARY",
                ),
                user=_Caller(),
                db=db,
            )
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "DUPLICATE_PRIMARY"


# ── Test 4: Transfer type config ─────────────────────────────────────────────

@pytest.mark.unit
class TestTransferTypeConfig:

    async def test_transfer_type_config_upsert(self) -> None:
        """PUT /transfer-types inserts a new config and stores level permissions."""
        from routers.transfer_types import upsert_transfer_types, TransferTypeConfigIn, LevelPermissionIn

        execute_calls: list[tuple[str, dict]] = []

        async def _capture(stmt, params=None, **kw) -> MagicMock:
            execute_calls.append((str(stmt), params or {}))
            res = MagicMock()
            res.fetchone = MagicMock(return_value=None)  # no existing → INSERT path
            res.fetchall = MagicMock(return_value=[])
            res.scalar   = MagicMock(return_value=0)
            return res

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=_capture)
        db.commit  = AsyncMock()

        with _GRANT_ALL:
            try:
                await upsert_transfer_types(
                    tenant_id=UUID(TENANT_ID),
                    body=[TransferTypeConfigIn(
                        underlying_type="PULL",
                        display_name="Pull Request",
                        level_permissions=[
                            LevelPermissionIn(level_number=3, can_initiate=False, can_receive=True)
                        ],
                    )],
                    user=_Caller(),
                    db=db,
                )
            except Exception:
                pass  # list call at end may fail on minimal mock; INSERT is what we verify

        stmts = " ".join(s for s, _ in execute_calls)
        assert "INSERT" in stmts, "Expected INSERT for new transfer type config"
        assert len(execute_calls) >= 3, "Expected: check existing + INSERT config + INSERT level perm"

    async def test_approval_rule_upsert(self) -> None:
        """PUT /transfer-approval-rules stores approval_steps as JSONB."""
        from routers.transfer_types import upsert_approval_rules, ApprovalRuleIn, ApprovalStepIn

        execute_calls: list[tuple[str, dict]] = []

        async def _capture(stmt, params=None, **kw) -> MagicMock:
            execute_calls.append((str(stmt), params or {}))
            res = MagicMock()
            res.fetchone = MagicMock(return_value=None)
            res.fetchall = MagicMock(return_value=[])
            res.scalar   = MagicMock(return_value=0)
            return res

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=_capture)
        db.commit  = AsyncMock()

        with _GRANT_ALL:
            try:
                await upsert_approval_rules(
                    tenant_id=UUID(TENANT_ID),
                    body=[ApprovalRuleIn(
                        transfer_type_config_id=UUID(CONFIG_ID),
                        source_level=3,
                        destination_level=2,
                        quantity_min=100,
                        quantity_max=5000,
                        threshold_type="QUANTITY",
                        approval_steps=[
                            ApprovalStepIn(
                                sequence=1,
                                position_title="Regional Manager",
                                sla_hours=24,
                            )
                        ],
                        priority=10,
                    )],
                    user=_Caller(),
                    db=db,
                )
            except Exception:
                pass

        stmts_params = [(s, p) for s, p in execute_calls]
        all_stmts = " ".join(s for s, _ in stmts_params)

        assert "DELETE" in all_stmts, "Expected DELETE before re-insert of rules"

        # Find INSERT params that include approval_steps
        insert_with_steps = [p for s, p in stmts_params if p.get("steps")]
        assert insert_with_steps, "Expected approval_steps in INSERT params"

        # steps is now a Python list (not JSON string) since we use bindparam(type_=types.JSON)
        raw_steps = insert_with_steps[0]["steps"]
        steps = raw_steps if isinstance(raw_steps, list) else json.loads(raw_steps)
        assert steps[0]["sequence"]       == 1
        assert steps[0]["position_title"] == "Regional Manager"
        assert steps[0]["sla_hours"]      == 24
