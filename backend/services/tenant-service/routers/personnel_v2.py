"""Personnel management v2 — users and position assignments.

Replaces personnel.py for the position-based model (Session 3+).
Users no longer carry role_code or warehouse_id on the users table;
those come from personnel_positions → positions.

GET    /tenants/{tenant_id}/users
POST   /tenants/{tenant_id}/users
POST   /tenants/{tenant_id}/users/{user_id}/positions
DELETE /tenants/{tenant_id}/users/{user_id}/positions/{assignment_id}
PATCH  /tenants/{tenant_id}/users/{user_id}/deactivate
PATCH  /tenants/{tenant_id}/users/{user_id}/reactivate
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import List, Optional

import bcrypt as _bcrypt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from shared.permissions.plan_middleware import check_plan_create_user

from dependencies import get_current_user, get_db_session_for_tenant
from shared.cache.login_lockout import _reset_login_attempts
from shared.permissions.audit import audit_log
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse

router = APIRouter()

# Roles that may be set directly via system_role (no position required) —
# tenant-wide accounts. TA is the original case; AU/LM are tenant-wide
# auditor / logistics-manager accounts created via the "Tenant-Wide Role"
# track in the Add User form.
VALID_DIRECT_SYSTEM_ROLES = {"TA", "AU", "LM"}


def _hash(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class PositionAssignmentOut(BaseModel):
    assignment_id:  uuid.UUID
    position_id:    uuid.UUID
    title:          str
    role_code:      str
    node_id:        uuid.UUID
    node_name:      str
    level_number:   int
    assignment_type: str
    valid_from:     Optional[date]
    valid_until:    Optional[date]


class UserOut(BaseModel):
    id:               uuid.UUID
    email:            str
    name:             str
    # role / facility fields for frontend UserRecord compatibility
    role:                   str                      # system_role or primary_position.role_code
    primary_facility_id:    Optional[uuid.UUID]      # primary_position.node_id
    primary_facility_name:  Optional[str]            # primary_position.node_name
    primary_position:       Optional[PositionAssignmentOut]
    acting_positions:       List[PositionAssignmentOut]
    is_active:              bool
    must_reset_password:    bool


class UserCreate(BaseModel):
    name:        str
    email:       EmailStr
    password:    str
    position_id: Optional[uuid.UUID] = None
    system_role: Optional[str] = None   # "TA"/"AU"/"LM" for tenant-wide accounts without a position
    role:        Optional[str] = None   # Frontend compat: if "TA", maps to system_role="TA"


class UserUpdateRequest(BaseModel):
    name:                Optional[str]       = None
    email:               Optional[EmailStr]  = None
    must_reset_password: Optional[bool]      = None
    system_role:         Optional[str]       = None
    role:                Optional[str]       = None  # Frontend compat: "TA" → system_role="TA"
    password:            Optional[str]       = None  # admin-initiated reset
    # system_role=None means "don't touch this column" (PATCH semantics can't
    # otherwise distinguish "not provided" from "clear it"). Set this explicitly
    # to NULL system_role — used when switching a user from a tenant-wide role
    # (Track B) back to a position-based one (Track A).
    clear_system_role:   bool                = False

    @field_validator("password")
    @classmethod
    def _validate_password_length(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class AssignPositionRequest(BaseModel):
    position_id:     uuid.UUID
    assignment_type: str = "PRIMARY"
    valid_from:      Optional[date] = None
    valid_until:     Optional[date] = None
    notes:           Optional[str]  = None


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _user_positions(
    db: AsyncSession, user_id: str, tenant_id: str,
) -> tuple[Optional[PositionAssignmentOut], List[PositionAssignmentOut]]:
    """Fetch primary + acting positions for a user."""
    rows = (await db.execute(
        text("""
            SELECT pp.id AS assignment_id, pp.assignment_type,
                   pp.valid_from, pp.valid_until,
                   p.id AS position_id, p.title, p.role_code,
                   n.id AS node_id, n.name AS node_name, n.hierarchy_level
            FROM   personnel_positions pp
            JOIN   positions p           ON p.id = pp.position_id
            JOIN   organization_node n   ON n.id = p.node_id
            WHERE  pp.user_id   = :uid
            AND    pp.tenant_id = :tid
            AND    pp.is_active = true
            AND    (pp.valid_until IS NULL OR pp.valid_until >= CURRENT_DATE)
            ORDER  BY pp.assignment_type, p.title
        """),
        {"uid": user_id, "tid": tenant_id},
    )).fetchall()

    primary: Optional[PositionAssignmentOut] = None
    acting:  List[PositionAssignmentOut]     = []
    for r in rows:
        ap = PositionAssignmentOut(
            assignment_id=r.assignment_id,
            position_id=r.position_id,
            title=r.title,
            role_code=r.role_code,
            node_id=r.node_id,
            node_name=r.node_name,
            level_number=r.hierarchy_level,
            assignment_type=r.assignment_type,
            valid_from=r.valid_from,
            valid_until=r.valid_until,
        )
        if r.assignment_type == "PRIMARY":
            primary = ap
        else:
            acting.append(ap)
    return primary, acting


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/{tenant_id}/users",
            response_model=SuccessResponse[List[UserOut]])
@require_permission(PERMISSIONS.USER_VIEW)
async def list_users(
    tenant_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[List[UserOut]]:
    """List all users for a tenant with their current position assignments."""
    rows = (await db.execute(
        text("""
            SELECT id, email, full_name, is_active, must_reset_password, system_role
            FROM   users
            WHERE  tenant_id = :tid
            ORDER  BY full_name
        """),
        {"tid": str(tenant_id)},
    )).fetchall()

    result: List[UserOut] = []
    for r in rows:
        primary, acting = await _user_positions(db, str(r.id), str(tenant_id))
        effective_role = (
            str(r.system_role) if r.system_role
            else (primary.role_code if primary else "—")
        )
        result.append(UserOut(
            id=r.id,
            email=r.email,
            name=r.full_name,
            role=effective_role,
            primary_facility_id=primary.node_id if primary else None,
            primary_facility_name=primary.node_name if primary else None,
            primary_position=primary,
            acting_positions=acting,
            is_active=r.is_active,
            must_reset_password=r.must_reset_password,
        ))
    return SuccessResponse(data=result)


@router.post("/{tenant_id}/users",
             status_code=201,
             response_model=SuccessResponse[UserOut])
@require_permission(PERMISSIONS.USER_CREATE)
async def create_user(
    tenant_id: uuid.UUID,
    body: UserCreate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[UserOut]:
    """Create a new user (no role_code — role comes from position assignment).

    If position_id is provided, a PRIMARY personnel_position is created immediately.
    """
    # Check for duplicate email within tenant
    existing = (await db.execute(
        text("SELECT id FROM users WHERE lower(email) = lower(:email) AND tenant_id = :tid"),
        {"email": body.email, "tid": str(tenant_id)},
    )).fetchone()
    if existing:
        raise HTTPException(
            status_code=409,
            detail={"code": "DUPLICATE_EMAIL", "message": f"Email '{body.email}' already exists."},
        )

    # Derive effective system_role: explicit field wins, then map role="TA" → "TA"
    effective_system_role = body.system_role or ("TA" if body.role == "TA" else None)
    if effective_system_role and effective_system_role not in VALID_DIRECT_SYSTEM_ROLES:
        raise HTTPException(status_code=422, detail={"code": "INVALID_SYSTEM_ROLE",
            "message": "system_role must be TA, AU, or LM, or null (role comes from position)."})

    # Role ceiling: only a platform admin (SA) may create another Tenant Admin.
    # A TA cannot create a peer/superior account — server-side, not just UI-hidden.
    if effective_system_role == "TA" and getattr(user, "role", None) != "SA":
        raise HTTPException(
            status_code=403,
            detail={"code": "ROLE_CEILING_EXCEEDED",
                    "message": "Only a platform administrator can create Tenant Administrator accounts."},
        )

    await check_plan_create_user(user, db)

    user_id = uuid.uuid4()
    await db.execute(
        text("""
            INSERT INTO users
              (id, tenant_id, email, full_name, password_hash,
               is_active, must_reset_password, system_role)
            VALUES (:id, :tid, :email, :name, :hash, true, true, :sysrole)
        """),
        {
            "id": str(user_id), "tid": str(tenant_id),
            "email": body.email, "name": body.name,
            "hash": _hash(body.password),
            "sysrole": effective_system_role,
        },
    )

    # Optionally assign primary position
    primary: Optional[PositionAssignmentOut] = None
    if body.position_id:
        pos_row = (await db.execute(
            text("""
                SELECT p.id, p.title, p.role_code,
                       n.id AS node_id, n.name AS node_name, n.hierarchy_level
                FROM   positions p
                JOIN   organization_node n ON n.id = p.node_id
                WHERE  p.id = :pid AND p.tenant_id = :tid AND p.is_active = true
            """),
            {"pid": str(body.position_id), "tid": str(tenant_id)},
        )).fetchone()
        if not pos_row:
            raise HTTPException(status_code=404, detail="Position not found")

        assignment_id = uuid.uuid4()
        await db.execute(
            text("""
                INSERT INTO personnel_positions
                  (id, tenant_id, user_id, position_id, assignment_type)
                VALUES (:id, :tid, :uid, :pid, 'PRIMARY')
            """),
            {"id": str(assignment_id), "tid": str(tenant_id),
             "uid": str(user_id), "pid": str(body.position_id)},
        )
        primary = PositionAssignmentOut(
            assignment_id=assignment_id,
            position_id=pos_row.id,
            title=pos_row.title,
            role_code=pos_row.role_code,
            node_id=pos_row.node_id,
            node_name=pos_row.node_name,
            level_number=pos_row.hierarchy_level,
            assignment_type="PRIMARY",
            valid_from=None,
            valid_until=None,
        )

    return SuccessResponse(data=UserOut(
        id=user_id,
        email=body.email,
        name=body.name,
        role=effective_system_role or (primary.role_code if primary else "—"),
        primary_facility_id=primary.node_id if primary else None,
        primary_facility_name=primary.node_name if primary else None,
        primary_position=primary,
        acting_positions=[],
        is_active=True,
        must_reset_password=True,
    ))


@router.post("/{tenant_id}/users/{user_id}/positions",
             status_code=201,
             response_model=SuccessResponse[PositionAssignmentOut])
@require_permission(PERMISSIONS.USER_MANAGE)
async def assign_position(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    body: AssignPositionRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[PositionAssignmentOut]:
    """Assign a user to a position.

    PRIMARY: only one active PRIMARY per user is allowed.
    ACTING/DELEGATE: time-bounded, multiple allowed.
    """
    if body.assignment_type not in ("PRIMARY", "ACTING", "DELEGATE"):
        raise HTTPException(status_code=422, detail="assignment_type must be PRIMARY, ACTING, or DELEGATE")

    # Self-lockout guard — see update_user(). Assigning any position to oneself
    # changes one's own effective role; only another admin may do this.
    if str(user.user_id) == str(user_id):
        raise HTTPException(
            status_code=403,
            detail={"code": "CANNOT_MODIFY_OWN_ROLE",
                    "message": "You cannot modify your own role or position."},
        )

    # Verify user belongs to this tenant
    user_row = (await db.execute(
        text("SELECT id FROM users WHERE id = :uid AND tenant_id = :tid AND is_active = true"),
        {"uid": str(user_id), "tid": str(tenant_id)},
    )).fetchone()
    if not user_row:
        raise HTTPException(status_code=404, detail="User not found in this tenant")

    # Swap PRIMARY atomically: deactivate any existing active PRIMARY before
    # inserting the new one, rather than rejecting the request. The caller
    # (Edit User UI) confirms the swap with the user before calling this.
    if body.assignment_type == "PRIMARY":
        await db.execute(
            text("""
                UPDATE personnel_positions
                SET is_active = false
                WHERE user_id = :uid AND assignment_type = 'PRIMARY'
                AND is_active = true
                AND (valid_until IS NULL OR valid_until >= CURRENT_DATE)
            """),
            {"uid": str(user_id)},
        )

    # Verify position belongs to this tenant
    pos_row = (await db.execute(
        text("""
            SELECT p.id, p.title, p.role_code,
                   n.id AS node_id, n.name AS node_name, n.hierarchy_level
            FROM   positions p
            JOIN   organization_node n ON n.id = p.node_id
            WHERE  p.id = :pid AND p.tenant_id = :tid AND p.is_active = true
        """),
        {"pid": str(body.position_id), "tid": str(tenant_id)},
    )).fetchone()
    if not pos_row:
        raise HTTPException(status_code=404, detail="Position not found")

    assignment_id = uuid.uuid4()
    from datetime import date as _date
    # Default valid_from to today if not provided — prevents NOT NULL violation when
    # the Edit User panel calls this endpoint without an explicit valid_from date.
    effective_valid_from = body.valid_from or _date.today()
    await db.execute(
        text("""
            INSERT INTO personnel_positions
              (id, tenant_id, user_id, position_id, assignment_type,
               valid_from, valid_until, notes)
            VALUES (:id, :tid, :uid, :pid, :atype,
                    :vf, :vu, :notes)
        """),
        {
            "id": str(assignment_id), "tid": str(tenant_id),
            "uid": str(user_id), "pid": str(body.position_id),
            "atype": body.assignment_type,
            "vf":    effective_valid_from, "vu": body.valid_until,
            "notes": body.notes,
        },
    )

    return SuccessResponse(data=PositionAssignmentOut(
        assignment_id=assignment_id,
        position_id=pos_row.id,
        title=pos_row.title,
        role_code=pos_row.role_code,
        node_id=pos_row.node_id,
        node_name=pos_row.node_name,
        level_number=pos_row.hierarchy_level,
        assignment_type=body.assignment_type,
        valid_from=body.valid_from,
        valid_until=body.valid_until,
    ))


@router.delete("/{tenant_id}/users/{user_id}/positions/{assignment_id}",
               response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.USER_MANAGE)
async def remove_position_assignment(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    assignment_id: uuid.UUID,
    force: bool = False,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[dict]:
    """Deactivate a position assignment.

    The last active PRIMARY assignment cannot be removed — use deactivate user instead.

    force=True is an SA-only escape hatch for correcting a wrong sole-PRIMARY
    assignment (e.g. a misassigned position) without first having a replacement
    position ready. It bypasses CANNOT_REMOVE_LAST_PRIMARY but auto-deactivates
    the user so they are never left active with zero positions.
    """
    # force is SA-only — any other caller (including TA) gets 403, regardless
    # of whether the removal would otherwise be blocked.
    if force and user.role != "SA":
        raise HTTPException(
            status_code=403,
            detail={"code": "FORCE_REMOVE_SA_ONLY",
                    "message": "The force flag may only be used by a platform administrator (SA)."},
        )

    # Self-lockout guard — see update_user(). Removing one's own position
    # assignment changes one's own effective role; only another admin may do this.
    if str(user.user_id) == str(user_id):
        raise HTTPException(
            status_code=403,
            detail={"code": "CANNOT_MODIFY_OWN_ROLE",
                    "message": "You cannot modify your own role or position."},
        )

    row = (await db.execute(
        text("""
            SELECT pp.id, pp.assignment_type
            FROM   personnel_positions pp
            JOIN   users u ON u.id = pp.user_id
            WHERE  pp.id        = :aid
            AND    pp.user_id   = :uid
            AND    pp.tenant_id = :tid
            AND    pp.is_active = true
        """),
        {"aid": str(assignment_id), "uid": str(user_id), "tid": str(tenant_id)},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Assignment not found or already inactive")

    # Cannot remove the last active PRIMARY — unless an SA explicitly forces it.
    user_deactivated = False
    if row.assignment_type == "PRIMARY":
        other_primary_count = (await db.execute(
            text("""
                SELECT COUNT(*) FROM personnel_positions
                WHERE user_id = :uid AND assignment_type = 'PRIMARY'
                AND is_active = true AND id != :aid
                AND (valid_until IS NULL OR valid_until >= CURRENT_DATE)
            """),
            {"uid": str(user_id), "aid": str(assignment_id)},
        )).scalar() or 0
        if other_primary_count == 0:
            if not force:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code":    "CANNOT_REMOVE_LAST_PRIMARY",
                        "message": "Cannot remove the user's only active PRIMARY assignment. "
                                   "Assign a new PRIMARY first, or deactivate the user.",
                    },
                )
            # SA force path: removing the user's only position would otherwise leave
            # them active with zero positions — deactivate them instead of allowing
            # that broken state, until they're given a correct reassignment.
            await db.execute(
                text("UPDATE users SET is_active = false, updated_at = now() WHERE id = :uid"),
                {"uid": str(user_id)},
            )
            user_deactivated = True
            await audit_log(
                user, PERMISSIONS.USER_MANAGE.id,
                {"resource_type": "personnel_position", "resource_id": str(assignment_id),
                 "tenant_id": str(tenant_id), "target_user_id": str(user_id)},
                "GRANTED",
                "SA force-removed sole PRIMARY position — user auto-deactivated pending reassignment",
            )

    await db.execute(
        text("UPDATE personnel_positions SET is_active = false WHERE id = :aid"),
        {"aid": str(assignment_id)},
    )
    return SuccessResponse(data={
        "deactivated": True,
        "assignment_id": str(assignment_id),
        "removed": True,
        "user_deactivated": user_deactivated,
    })


@router.patch("/{tenant_id}/users/{user_id}/deactivate",
              response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.USER_MANAGE)
async def deactivate_user(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[dict]:
    """Deactivate user and close all active position assignments.

    Two guards prevent a tenant from locking itself out:
      - A caller can never deactivate their own account.
      - The last active TA in a tenant cannot be deactivated.
    """
    if str(user.user_id) == str(user_id):
        raise HTTPException(
            status_code=422,
            detail={"code": "CANNOT_DEACTIVATE_SELF",
                    "message": "You cannot deactivate your own account."},
        )

    row = (await db.execute(
        text("SELECT id, system_role FROM users WHERE id = :uid AND tenant_id = :tid AND is_active = true"),
        {"uid": str(user_id), "tid": str(tenant_id)},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found or already inactive")

    if row.system_role == "TA":
        active_ta_count = (await db.execute(
            text("""
                SELECT COUNT(*) FROM users
                WHERE tenant_id = :tid AND system_role = 'TA' AND is_active = true
            """),
            {"tid": str(tenant_id)},
        )).scalar() or 0
        if active_ta_count <= 1:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "CANNOT_DEACTIVATE_LAST_TA",
                    "message": "Cannot deactivate the last active Tenant Administrator. "
                               "Assign another TA first or contact your platform administrator.",
                },
            )

    await db.execute(
        text("UPDATE users SET is_active = false, updated_at = now() WHERE id = :uid"),
        {"uid": str(user_id)},
    )
    await db.execute(
        text("UPDATE personnel_positions SET is_active = false WHERE user_id = :uid AND tenant_id = :tid"),
        {"uid": str(user_id), "tid": str(tenant_id)},
    )
    return SuccessResponse(data={"deactivated": True, "user_id": str(user_id)})


@router.patch("/{tenant_id}/users/{user_id}/reactivate",
              response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.USER_MANAGE)
async def reactivate_user(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    restore_position: bool = True,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[dict]:
    """Reactivate a deactivated user.

    By default (restore_position=True) the user's most recent PRIMARY
    personnel_positions row is restored alongside the user record, provided
    it is currently inactive and has not legitimately expired (valid_until IS NULL
    OR valid_until >= today). Only the newest PRIMARY row (by created_at DESC) is
    considered — older swapped-out PRIMARY rows are left untouched. ACTING and
    DELEGATE rows are never restored by this endpoint.

    Pass restore_position=False to reactivate the user account only, leaving
    position reassignment to a follow-up POST /positions call.
    """
    row = (await db.execute(
        text("SELECT id, system_role FROM users WHERE id = :uid AND tenant_id = :tid AND is_active = false"),
        {"uid": str(user_id), "tid": str(tenant_id)},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found or already active")

    # Enforce the plan user cap — reactivating a non-TA counts the same as creating one.
    if row.system_role != "TA":
        await check_plan_create_user(user, db)

    await db.execute(
        text("UPDATE users SET is_active = true, updated_at = now() WHERE id = :uid"),
        {"uid": str(user_id)},
    )

    pos_restored = False
    if restore_position:
        pp_row = (await db.execute(
            text("""
                SELECT id, is_active, valid_until
                FROM   personnel_positions
                WHERE  user_id         = :uid
                AND    tenant_id       = :tid
                AND    assignment_type = 'PRIMARY'
                ORDER  BY created_at DESC
                LIMIT  1
            """),
            {"uid": str(user_id), "tid": str(tenant_id)},
        )).fetchone()
        if (
            pp_row is not None
            and not pp_row.is_active
            and (pp_row.valid_until is None or pp_row.valid_until >= date.today())
        ):
            await db.execute(
                text("UPDATE personnel_positions SET is_active = true WHERE id = :pid"),
                {"pid": str(pp_row.id)},
            )
            pos_restored = True

    return SuccessResponse(data={
        "reactivated": True,
        "user_id": str(user_id),
        "position_restored": pos_restored,
    })


@router.get("/{tenant_id}/users/{user_id}",
            response_model=SuccessResponse[UserOut])
@require_permission(PERMISSIONS.USER_VIEW)
async def get_user(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[UserOut]:
    """Fetch a single user with their position assignments."""
    row = (await db.execute(
        text("""
            SELECT id, email, full_name, is_active, must_reset_password, system_role
            FROM   users
            WHERE  id = :uid AND tenant_id = :tid
        """),
        {"uid": str(user_id), "tid": str(tenant_id)},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    primary, acting = await _user_positions(db, str(user_id), str(tenant_id))
    effective_role = (
        str(row.system_role) if row.system_role
        else (primary.role_code if primary else "—")
    )
    return SuccessResponse(data=UserOut(
        id=row.id,
        email=row.email,
        name=row.full_name,
        role=effective_role,
        primary_facility_id=primary.node_id if primary else None,
        primary_facility_name=primary.node_name if primary else None,
        primary_position=primary,
        acting_positions=acting,
        is_active=row.is_active,
        must_reset_password=row.must_reset_password,
    ))


@router.patch("/{tenant_id}/users/{user_id}",
              response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.USER_MANAGE)
async def update_user(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    body: UserUpdateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[dict]:
    """Update user name, email, password-reset flag, or system_role.

    Role comes from position assignments, not this endpoint — except for TA
    accounts (system_role='TA') which have no position. Sending role='TA' maps
    to system_role='TA' for backward compatibility with the frontend.
    """
    # Self-lockout guard: a user (e.g. a TA) who clears or changes their own
    # system_role could strip their own admin access with no recovery path
    # short of SA intervention. Name/email/password fields on the caller's own
    # record are still allowed through this same endpoint.
    if str(user.user_id) == str(user_id) and (
        body.system_role is not None or body.role is not None or body.clear_system_role
    ):
        raise HTTPException(
            status_code=403,
            detail={"code": "CANNOT_MODIFY_OWN_ROLE",
                    "message": "You cannot modify your own role or position."},
        )

    row = (await db.execute(
        text("SELECT id, email FROM users WHERE id = :uid AND tenant_id = :tid"),
        {"uid": str(user_id), "tid": str(tenant_id)},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    set_parts: list[str] = ["updated_at = now()"]
    params: dict = {"uid": str(user_id), "tid": str(tenant_id)}

    if body.name is not None:
        set_parts.append("full_name = :name")
        params["name"] = body.name.strip()
    if body.email is not None:
        set_parts.append("email = :email")
        params["email"] = str(body.email).lower()
    if body.must_reset_password is not None:
        set_parts.append("must_reset_password = :mrp")
        params["mrp"] = body.must_reset_password

    if body.password is not None:
        set_parts.append("password_hash = :ph")
        params["ph"] = _hash(body.password)
        # Resetting a password always forces a change on next login —
        # overrides any explicit must_reset_password value set above.
        if "must_reset_password = :mrp" not in set_parts:
            set_parts.append("must_reset_password = :mrp")
        params["mrp"] = True

    if body.clear_system_role:
        set_parts.append("system_role = NULL")
    else:
        # system_role: explicit field or mapped from legacy role="TA"
        effective_sr = body.system_role or ("TA" if body.role == "TA" else None)
        if effective_sr is not None:
            if effective_sr not in VALID_DIRECT_SYSTEM_ROLES:
                raise HTTPException(
                    status_code=422,
                    detail={"code": "INVALID_SYSTEM_ROLE",
                            "message": "system_role must be TA, AU, or LM, or null (role comes from position)."},
                )
            set_parts.append("system_role = :sr")
            params["sr"] = effective_sr

    await db.execute(
        text(f"UPDATE users SET {', '.join(set_parts)} WHERE id = :uid AND tenant_id = :tid"),
        params,
    )

    if body.password is not None:
        # A TA-issued password reset immediately unblocks a locked-out user —
        # no need to wait out the 15-minute Redis lockout window. Reset against
        # the user's email AS OF BEFORE this update (the email they were
        # actually failing login attempts under), not any new email also
        # being set in this same request.
        await _reset_login_attempts(row.email)

    return SuccessResponse(data={"updated": True, "user_id": str(user_id)})
