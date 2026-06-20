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
# redis.from_url() doesn't connect eagerly — this only satisfies the module-level
# os.environ["REDIS_URL"] read in shared.cache.redis_client (personnel_v2.py now
# imports shared.cache.login_lockout for the password-reset lockout-clear call).
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

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

    async def test_create_user_with_position(self) -> None:
        """POST /users creates the user AND the PRIMARY personnel_position atomically —
        a single call into create_user, with no separate POST .../positions needed."""
        from routers.personnel_v2 import create_user, UserCreate

        pos_row = _row(id=POSITION_ID, title="Main WH Manager", role_code="WM",
                       node_id=NODE_ID, node_name="Main WH", hierarchy_level=1)

        execute_calls: list[tuple[str, dict]] = []

        async def _capture(stmt, params=None, **kw) -> MagicMock:
            execute_calls.append((str(stmt), params or {}))
            res = MagicMock()
            if "SELECT id FROM users" in str(stmt):
                res.fetchone = MagicMock(return_value=None)       # no duplicate email
            elif "SELECT p.id, p.title, p.role_code" in str(stmt):
                res.fetchone = MagicMock(return_value=pos_row)    # position lookup
            else:
                res.fetchone = MagicMock(return_value=None)       # INSERT statements
            return res

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=_capture)

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

        # Exactly one create_user() invocation produced both the user row and the
        # PRIMARY assignment row — no second endpoint call was needed.
        stmts = " ".join(s for s, _ in execute_calls)
        assert "INSERT INTO users" in stmts
        assert "INSERT INTO personnel_positions" in stmts
        assert len(execute_calls) == 4, "dup-email check + INSERT user + position lookup + INSERT assignment"

    async def test_swap_primary_position_success(self) -> None:
        """POST /users/{id}/positions with assignment_type=PRIMARY deactivates the user's
        existing PRIMARY row and inserts the new one, instead of rejecting the request —
        the Edit User UI confirms the swap with the caller before calling this endpoint."""
        from routers.personnel_v2 import assign_position, AssignPositionRequest

        user_row = _row(id=USER_ID)
        pos_row  = _row(id=POSITION_ID, title="Main WH Manager", role_code="WM",
                        node_id=NODE_ID, node_name="Main WH", hierarchy_level=1)

        execute_calls: list[tuple[str, dict]] = []

        async def _capture(stmt, params=None, **kw) -> MagicMock:
            execute_calls.append((str(stmt), params or {}))
            res = MagicMock()
            if "SELECT id FROM users" in str(stmt):
                res.fetchone = MagicMock(return_value=user_row)
            elif "SELECT p.id, p.title, p.role_code" in str(stmt):
                res.fetchone = MagicMock(return_value=pos_row)
            else:
                res.fetchone = MagicMock(return_value=None)
            return res

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=_capture)

        with _GRANT_ALL:
            result = await assign_position(
                tenant_id=UUID(TENANT_ID),
                user_id=UUID(USER_ID),
                body=AssignPositionRequest(
                    position_id=UUID(POSITION_ID),
                    assignment_type="PRIMARY",
                ),
                user=_Caller(),
                db=db,
            )

        assert result.data.role_code == "WM"
        assert result.data.assignment_type == "PRIMARY"

        # The deactivate-old-PRIMARY UPDATE must run before the INSERT of the new
        # PRIMARY row, so at no point do two active PRIMARY rows coexist.
        update_idx = next(i for i, (s, _) in enumerate(execute_calls) if "is_active = false" in s)
        insert_idx = next(i for i, (s, _) in enumerate(execute_calls) if "INSERT INTO personnel_positions" in s)
        assert update_idx < insert_idx
        update_stmt, update_params = execute_calls[update_idx]
        assert "assignment_type = 'PRIMARY'" in update_stmt
        assert update_params["uid"] == USER_ID

    async def test_swap_primary_same_position_is_a_no_op_swap(self) -> None:
        """Documenting actual behavior: assign_position does NOT special-case
        'new position_id equals the current PRIMARY's position_id'. It still
        deactivates the existing row and inserts a fresh one at the same position —
        not a 422. (The frontend already avoids calling this endpoint at all when
        the selected position matches the current one — see isPositionChange in
        settings/personnel/page.tsx — so this path is reachable only via direct API use.)"""
        from routers.personnel_v2 import assign_position, AssignPositionRequest

        user_row = _row(id=USER_ID)
        pos_row  = _row(id=POSITION_ID, title="Main WH Manager", role_code="WM",
                        node_id=NODE_ID, node_name="Main WH", hierarchy_level=1)

        db = _db_seq(
            user_row,  # user belongs to tenant
            None,      # UPDATE — deactivate existing PRIMARY (same position)
            pos_row,   # position lookup — same position_id as before
            None,      # INSERT — new PRIMARY row at the same position
        )

        with _GRANT_ALL:
            result = await assign_position(
                tenant_id=UUID(TENANT_ID),
                user_id=UUID(USER_ID),
                body=AssignPositionRequest(
                    position_id=UUID(POSITION_ID),
                    assignment_type="PRIMARY",
                ),
                user=_Caller(),
                db=db,
            )

        # No exception — a new assignment row is created even though the position
        # didn't change. This is a documented quirk, not the happy path the UI uses.
        assert result.data.position_id == UUID(POSITION_ID)
        assert result.data.assignment_type == "PRIMARY"

    async def test_remove_acting_assignment(self) -> None:
        """DELETE /users/{id}/positions/{assignment_id} deactivates an ACTING row
        without touching the user's PRIMARY assignment or requiring another PRIMARY
        to exist (the other-PRIMARY-count guard only applies to PRIMARY removals)."""
        from routers.personnel_v2 import remove_position_assignment

        assignment_row = _row(id=POSITION_ID, assignment_type="ACTING")

        execute_calls: list[tuple[str, dict]] = []

        async def _capture(stmt, params=None, **kw) -> MagicMock:
            execute_calls.append((str(stmt), params or {}))
            res = MagicMock()
            res.fetchone = MagicMock(return_value=assignment_row if "SELECT pp.id" in str(stmt) else None)
            return res

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=_capture)

        with _GRANT_ALL:
            result = await remove_position_assignment(
                tenant_id=UUID(TENANT_ID),
                user_id=UUID(USER_ID),
                assignment_id=UUID(POSITION_ID),
                user=_Caller(),
                db=db,
            )

        assert result.data == {"deactivated": True, "assignment_id": POSITION_ID}
        stmts = " ".join(s for s, _ in execute_calls)
        assert "UPDATE personnel_positions SET is_active = false" in stmts
        # ACTING removal never queries for other active PRIMARY rows.
        assert "COUNT(*)" not in stmts

    async def test_cannot_remove_last_primary(self) -> None:
        """DELETE /users/{id}/positions/{assignment_id} rejects removing a user's only
        active PRIMARY assignment — existing guard preserved by the swap change above,
        which only touches assign_position, not remove_position_assignment."""
        from routers.personnel_v2 import remove_position_assignment

        assignment_row = _row(id=POSITION_ID, assignment_type="PRIMARY")

        db = _db_seq(
            assignment_row,  # assignment found and active
            0,                # other_primary_count == 0 → only this PRIMARY exists
        )

        with _GRANT_ALL, pytest.raises(HTTPException) as exc_info:
            await remove_position_assignment(
                tenant_id=UUID(TENANT_ID),
                user_id=UUID(USER_ID),
                assignment_id=UUID(POSITION_ID),
                user=_Caller(),
                db=db,
            )

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "CANNOT_REMOVE_LAST_PRIMARY"

    async def test_ta_can_reset_user_password(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """PATCH /users/{id} with password hashes it into password_hash and forces
        must_reset_password=True, even if must_reset_password wasn't explicitly set —
        the user must change the admin-issued temporary password on next login.
        Also clears the user's Redis login-lockout counter immediately."""
        from routers.personnel_v2 import update_user, UserUpdateRequest

        user_row = _row(id=USER_ID, email="locked-out@test.com")
        execute_calls: list[tuple[str, dict]] = []

        async def _capture(stmt, params=None, **kw) -> MagicMock:
            execute_calls.append((str(stmt), params or {}))
            res = MagicMock()
            res.fetchone = MagicMock(return_value=user_row if "FROM users WHERE id" in str(stmt) else None)
            return res

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=_capture)

        reset_calls: list[str] = []

        async def _fake_reset(email: str) -> None:
            reset_calls.append(email)

        monkeypatch.setattr("routers.personnel_v2._reset_login_attempts", _fake_reset)

        with _GRANT_ALL:
            result = await update_user(
                tenant_id=UUID(TENANT_ID),
                user_id=UUID(USER_ID),
                body=UserUpdateRequest(password="NewPass@2026"),
                user=_Caller(),
                db=db,
            )

        assert result.data == {"updated": True, "user_id": USER_ID}
        update_stmt, update_params = execute_calls[-1]
        assert "password_hash = :ph" in update_stmt
        assert "must_reset_password = :mrp" in update_stmt
        assert update_params["mrp"] is True
        assert update_params["ph"] != "NewPass@2026"  # stored as a bcrypt hash, never plaintext
        assert reset_calls == ["locked-out@test.com"]

    async def test_reset_password_requires_min_length(self) -> None:
        """UserUpdateRequest rejects passwords under 8 characters at the schema
        level — FastAPI turns this into a 422 before update_user() ever runs."""
        from routers.personnel_v2 import UserUpdateRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            UserUpdateRequest(password="short1")

        # 8 characters is the floor — this must NOT raise.
        UserUpdateRequest(password="exactly8")

    async def test_reset_password_not_in_get_response(self) -> None:
        """UserOut never exposes password_hash — defence in depth so a reset
        password's hash can never be read back through any GET endpoint."""
        from routers.personnel_v2 import UserOut

        assert "password_hash" not in UserOut.model_fields

    async def test_cannot_deactivate_self(self) -> None:
        """PATCH /users/{id}/deactivate rejects a caller deactivating their own
        account — checked before any row is even queried."""
        from routers.personnel_v2 import deactivate_user

        db = _db_seq()  # no DB calls should be needed — guard fires first

        with _GRANT_ALL, pytest.raises(HTTPException) as exc_info:
            await deactivate_user(
                tenant_id=UUID(TENANT_ID),
                user_id=UUID(USER_ID),
                user=_Caller(user_id=USER_ID),
                db=db,
            )

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "CANNOT_DEACTIVATE_SELF"

    async def test_cannot_deactivate_last_ta(self) -> None:
        """PATCH /users/{id}/deactivate rejects deactivating a TA when they are
        the only active TA left in the tenant."""
        from routers.personnel_v2 import deactivate_user

        target_row = _row(id=USER_ID, system_role="TA")
        db = _db_seq(
            target_row,  # target user found, active
            1,           # active_ta_count == 1 → only this TA exists
        )

        with _GRANT_ALL, pytest.raises(HTTPException) as exc_info:
            await deactivate_user(
                tenant_id=UUID(TENANT_ID),
                user_id=UUID(USER_ID),
                user=_Caller(user_id="caller-001"),
                db=db,
            )

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "CANNOT_DEACTIVATE_LAST_TA"

    async def test_can_deactivate_ta_if_another_exists(self) -> None:
        """PATCH /users/{id}/deactivate succeeds for a TA when at least one other
        active TA remains in the tenant."""
        from routers.personnel_v2 import deactivate_user

        target_row = _row(id=USER_ID, system_role="TA")
        db = _db_seq(
            target_row,  # target user found, active
            2,           # active_ta_count == 2 → another TA exists
            None,        # UPDATE users SET is_active=false
            None,        # UPDATE personnel_positions SET is_active=false
        )

        with _GRANT_ALL:
            result = await deactivate_user(
                tenant_id=UUID(TENANT_ID),
                user_id=UUID(USER_ID),
                user=_Caller(user_id="caller-001"),
                db=db,
            )

        assert result.data == {"deactivated": True, "user_id": USER_ID}

    async def test_create_user_accepts_au_system_role(self) -> None:
        """POST /users accepts system_role='AU' for the tenant-wide Auditor
        track (Track B in the Add User form) — no position_id required."""
        from routers.personnel_v2 import create_user, UserCreate

        db = _db_seq(
            None,  # no duplicate email
            None,  # INSERT users
        )

        with _GRANT_ALL:
            result = await create_user(
                tenant_id=UUID(TENANT_ID),
                body=UserCreate(
                    name="Almaz Tesfaye",
                    email="almaz@test.com",
                    password="TestPass@2026",
                    system_role="AU",
                ),
                user=_Caller(),
                db=db,
            )

        assert result.data.role == "AU"
        assert result.data.primary_position is None

    async def test_create_user_accepts_lm_system_role(self) -> None:
        """POST /users accepts system_role='LM' for the tenant-wide Logistics
        Manager track."""
        from routers.personnel_v2 import create_user, UserCreate

        db = _db_seq(None, None)

        with _GRANT_ALL:
            result = await create_user(
                tenant_id=UUID(TENANT_ID),
                body=UserCreate(
                    name="Dawit Alemu",
                    email="dawit@test.com",
                    password="TestPass@2026",
                    system_role="LM",
                ),
                user=_Caller(),
                db=db,
            )

        assert result.data.role == "LM"
        assert result.data.primary_position is None

    async def test_create_user_rejects_invalid_system_role(self) -> None:
        """POST /users still rejects system_role values outside {TA, AU, LM} —
        e.g. a facility role like WM must come from position_id, never directly."""
        from routers.personnel_v2 import create_user, UserCreate

        db = _db_seq(None)  # no duplicate email — should not get further

        with _GRANT_ALL, pytest.raises(HTTPException) as exc_info:
            await create_user(
                tenant_id=UUID(TENANT_ID),
                body=UserCreate(
                    name="Invalid Role",
                    email="invalid@test.com",
                    password="TestPass@2026",
                    system_role="WM",
                ),
                user=_Caller(),
                db=db,
            )

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "INVALID_SYSTEM_ROLE"

    async def test_ta_cannot_create_ta(self) -> None:
        """POST /users with system_role='TA' is rejected for a TA caller — only
        a platform admin (SA) may create another Tenant Admin account."""
        from routers.personnel_v2 import create_user, UserCreate

        db = _db_seq(None)  # no duplicate email — should not get further

        with _GRANT_ALL, pytest.raises(HTTPException) as exc_info:
            await create_user(
                tenant_id=UUID(TENANT_ID),
                body=UserCreate(
                    name="Second Admin",
                    email="second-admin@test.com",
                    password="TestPass@2026",
                    system_role="TA",
                ),
                user=_Caller(role="TA"),
                db=db,
            )

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["code"] == "ROLE_CEILING_EXCEEDED"

    async def test_sa_can_create_ta(self) -> None:
        """POST /users with system_role='TA' succeeds for an SA (platform admin)
        caller — the role ceiling only blocks TA-creating-TA, not SA."""
        from routers.personnel_v2 import create_user, UserCreate

        db = _db_seq(
            None,  # no duplicate email
            None,  # INSERT users
        )

        with _GRANT_ALL:
            result = await create_user(
                tenant_id=UUID(TENANT_ID),
                body=UserCreate(
                    name="Second Admin",
                    email="second-admin@test.com",
                    password="TestPass@2026",
                    system_role="TA",
                ),
                user=_Caller(role="SA"),
                db=db,
            )

        assert result.data.role == "TA"
        assert result.data.primary_position is None

    async def test_ta_cannot_modify_own_role(self) -> None:
        """PATCH /users/{id} rejects a caller changing their own system_role —
        a TA who clears or reassigns their own role could lock themselves out
        of admin access with no recovery path short of SA intervention. Other
        fields (name, email, password) on the caller's own record remain
        editable through this same endpoint."""
        from routers.personnel_v2 import update_user, UserUpdateRequest

        db = _db_seq()  # no DB calls should be needed — guard fires first

        with _GRANT_ALL, pytest.raises(HTTPException) as exc_info:
            await update_user(
                tenant_id=UUID(TENANT_ID),
                user_id=UUID(USER_ID),
                body=UserUpdateRequest(system_role="AU"),
                user=_Caller(user_id=USER_ID),
                db=db,
            )

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["code"] == "CANNOT_MODIFY_OWN_ROLE"

    async def test_clear_system_role_on_update(self) -> None:
        """PATCH /users/{id} with clear_system_role=True nulls out system_role —
        used when switching a user from a tenant-wide role (Track B) back to a
        position-based one (Track A), so role then comes from the new position
        instead of the stale system_role value."""
        from routers.personnel_v2 import update_user, UserUpdateRequest

        user_row = _row(id=USER_ID)
        execute_calls: list[tuple[str, dict]] = []

        async def _capture(stmt, params=None, **kw) -> MagicMock:
            execute_calls.append((str(stmt), params or {}))
            res = MagicMock()
            res.fetchone = MagicMock(return_value=user_row if "FROM users WHERE id" in str(stmt) else None)
            return res

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=_capture)

        with _GRANT_ALL:
            result = await update_user(
                tenant_id=UUID(TENANT_ID),
                user_id=UUID(USER_ID),
                body=UserUpdateRequest(clear_system_role=True),
                user=_Caller(),
                db=db,
            )

        assert result.data == {"updated": True, "user_id": USER_ID}
        update_stmt, _ = execute_calls[-1]
        assert "system_role = NULL" in update_stmt


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
