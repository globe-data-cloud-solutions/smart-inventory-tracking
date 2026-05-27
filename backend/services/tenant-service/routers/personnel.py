"""Personnel management endpoints — users and facility assignments.

Users:       GET/POST /tenants/{tenant_id}/users
             PATCH    /tenants/{tenant_id}/users/{user_id}
             POST     /tenants/{tenant_id}/users/{user_id}/deactivate
             POST     /tenants/{tenant_id}/users/{user_id}/reactivate
Assignments: POST     /tenants/{tenant_id}/users/{user_id}/assignments
             DELETE   /tenants/{tenant_id}/users/{user_id}/assignments/{assignment_id}
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

import bcrypt as _bcrypt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def _verify_password(password: str, hashed: str) -> bool:
    return _bcrypt.checkpw(password.encode(), hashed.encode())

from dependencies import get_current_user, get_db_session, get_db_session_for_tenant
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse

router = APIRouter()

# Role privilege levels — higher = more privilege
ROLE_LEVELS: dict[str, int] = {
    "SYS": 1, "AU": 2, "RT": 3, "SA_GT": 4,
    "LM": 6, "WM": 6, "RM": 7, "NM": 8, "TA": 9, "SA": 10,
}


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class AssignmentOut(BaseModel):
    id: uuid.UUID
    facility_id: uuid.UUID
    facility_name: Optional[str]
    assignment_type: str
    role_code: str
    valid_from: datetime
    valid_until: Optional[datetime]
    notes: Optional[str]
    is_active: bool


class UserOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    email: str
    name: str                           # full_name alias for frontend compatibility
    role: str
    primary_facility_id: Optional[uuid.UUID]
    primary_facility_name: Optional[str]
    is_active: bool
    created_at: Optional[datetime] = None
    assignments: List[AssignmentOut] = []


class UserCreateRequest(BaseModel):
    name: str                           # full_name alias for frontend compatibility
    email: EmailStr
    role: str                           # role_code alias for frontend compatibility
    facility_id: Optional[uuid.UUID] = None   # optional for TA/SA-level roles
    password: Optional[str] = None


class UserUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    role_code: Optional[str] = None
    facility_id: Optional[uuid.UUID] = None


class AssignmentCreateRequest(BaseModel):
    facility_id: uuid.UUID
    assignment_type: str   # ACTING | DELEGATE
    role_code: Optional[str] = None
    valid_from: Optional[datetime] = None
    valid_until: datetime
    notes: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_authority_scope(
    db: AsyncSession, tenant_id: str, facility_id: str
) -> list[str]:
    """Return all organization_node IDs that facility_id has authority over."""
    rows = await db.execute(
        text(
            """
            WITH RECURSIVE authority_tree AS (
                SELECT from_node_id AS node_id
                FROM org_node_hierarchy
                WHERE tenant_id = :tid
                  AND to_node_id = :fid::uuid
                  AND relationship_type = 'PRIMARY_REPORTS_TO'
                UNION ALL
                SELECT h.from_node_id
                FROM org_node_hierarchy h
                INNER JOIN authority_tree a ON h.to_node_id = a.node_id
                WHERE h.tenant_id = :tid
                  AND h.relationship_type = 'PRIMARY_REPORTS_TO'
            )
            SELECT node_id FROM authority_tree
            """
        ),
        {"tid": tenant_id, "fid": facility_id},
    )
    return [str(r[0]) for r in rows.fetchall()]


async def _get_user_assignments(
    db: AsyncSession, user_id: str
) -> list[AssignmentOut]:
    rows = await db.execute(
        text(
            """
            SELECT ufa.id, ufa.facility_id, n.name AS facility_name,
                   ufa.assignment_type, ufa.role_code, ufa.valid_from,
                   ufa.valid_until, ufa.notes, ufa.is_active
            FROM user_facility_assignments ufa
            LEFT JOIN organization_node n ON n.id = ufa.facility_id
            WHERE ufa.user_id = :uid AND ufa.is_active = true
            ORDER BY ufa.assignment_type, ufa.valid_from
            """
        ),
        {"uid": user_id},
    )
    return [
        AssignmentOut(
            id=r.id,
            facility_id=r.facility_id,
            facility_name=r.facility_name,
            assignment_type=r.assignment_type,
            role_code=r.role_code,
            valid_from=r.valid_from,
            valid_until=r.valid_until,
            notes=r.notes,
            is_active=r.is_active,
        )
        for r in rows.fetchall()
    ]


def _check_role_ceiling(caller_role: str, target_role: str) -> None:
    """Raise 403 if caller tries to assign a role at or above their own level."""
    caller_level = ROLE_LEVELS.get(caller_role, 0)
    target_level = ROLE_LEVELS.get(target_role, 0)
    if target_level >= caller_level:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "ROLE_CEILING_VIOLATION",
                "message": f"Cannot assign role '{target_role}' — "
                           f"it is at or above your own privilege level.",
            },
        )


# ── User list ─────────────────────────────────────────────────────────────────

@router.get(
    "/{tenant_id}/users",
    response_model=SuccessResponse[List[UserOut]],
)
@require_permission(PERMISSIONS.USER_VIEW)
async def list_users(
    tenant_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[List[UserOut]]:
    tid = str(tenant_id)

    # Determine scoped facility IDs based on caller's role
    caller_wh = getattr(user, "warehouse_id", None)
    caller_role = getattr(user, "role", "WM")
    caller_role_level = ROLE_LEVELS.get(caller_role, 0)

    scoped_facility_ids: Optional[list[str]] = None
    if caller_role_level < ROLE_LEVELS.get("NM", 8) and caller_wh:
        # WM/RM/LM — scope to their subtree
        subtree = await _get_authority_scope(db, tid, str(caller_wh))
        scoped_facility_ids = subtree + [str(caller_wh)]

    if scoped_facility_ids is not None:
        rows = await db.execute(
            text(
                """
                SELECT u.id, u.tenant_id, u.email, u.full_name AS name, u.role,
                       u.warehouse_id AS primary_facility_id,
                       n.name AS primary_facility_name, u.is_active, u.created_at
                FROM users u
                LEFT JOIN organization_node n ON n.id = u.warehouse_id
                WHERE u.tenant_id = :tid
                  AND u.warehouse_id = ANY(:wids)
                ORDER BY u.full_name
                """
            ),
            {"tid": tid, "wids": scoped_facility_ids},
        )
    else:
        rows = await db.execute(
            text(
                """
                SELECT u.id, u.tenant_id, u.email, u.full_name AS name, u.role,
                       u.warehouse_id AS primary_facility_id,
                       n.name AS primary_facility_name, u.is_active, u.created_at
                FROM users u
                LEFT JOIN organization_node n ON n.id = u.warehouse_id
                WHERE u.tenant_id = :tid
                ORDER BY u.full_name
                """
            ),
            {"tid": tid},
        )

    user_rows = rows.fetchall()
    users_out = []
    for r in user_rows:
        assignments = await _get_user_assignments(db, str(r.id))
        users_out.append(
            UserOut(
                id=r.id,
                tenant_id=r.tenant_id,
                email=r.email,
                name=r.name,
                role=r.role,
                primary_facility_id=r.primary_facility_id,
                primary_facility_name=r.primary_facility_name,
                is_active=r.is_active,
                created_at=r.created_at,
                assignments=assignments,
            )
        )
    return SuccessResponse(data=users_out)


# ── Get single user ───────────────────────────────────────────────────────────

@router.get(
    "/{tenant_id}/users/{user_id}",
    response_model=SuccessResponse[UserOut],
)
@require_permission(PERMISSIONS.USER_VIEW)
async def get_user(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[UserOut]:
    row = await db.execute(
        text(
            """
            SELECT u.id, u.tenant_id, u.email, u.full_name AS name, u.role,
                   u.warehouse_id AS primary_facility_id,
                   n.name AS primary_facility_name, u.is_active, u.created_at
            FROM users u
            LEFT JOIN organization_node n ON n.id = u.warehouse_id
            WHERE u.id = :uid AND u.tenant_id = :tid
            """
        ),
        {"uid": str(user_id), "tid": str(tenant_id)},
    )
    r = row.fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="User not found")
    assignments = await _get_user_assignments(db, str(user_id))
    return SuccessResponse(
        data=UserOut(
            id=r.id,
            tenant_id=r.tenant_id,
            email=r.email,
            name=r.name,
            role=r.role,
            primary_facility_id=r.primary_facility_id,
            primary_facility_name=r.primary_facility_name,
            is_active=r.is_active,
            created_at=r.created_at,
            assignments=assignments,
        )
    )


# ── Create user ───────────────────────────────────────────────────────────────

@router.post(
    "/{tenant_id}/users",
    status_code=201,
    response_model=SuccessResponse[UserOut],
)
@require_permission(PERMISSIONS.USER_CREATE)
async def create_user(
    tenant_id: uuid.UUID,
    body: UserCreateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[UserOut]:
    tid = str(tenant_id)
    caller_role = getattr(user, "role", "SA")

    # Enforce role ceiling — cannot create user with role >= caller's level
    _check_role_ceiling(caller_role, body.role)

    # Validate facility belongs to this tenant (if provided)
    facility = None
    if body.facility_id is not None:
        fac_row = await db.execute(
            text(
                "SELECT id, name FROM organization_node "
                "WHERE id = :fid AND tenant_id = :tid AND is_active = true"
            ),
            {"fid": str(body.facility_id), "tid": tid},
        )
        facility = fac_row.fetchone()
        if not facility:
            raise HTTPException(status_code=422, detail="facility_id not found in this tenant")

    # Check email uniqueness within tenant
    existing = await db.execute(
        text("SELECT id FROM users WHERE email = :email AND tenant_id = :tid"),
        {"email": body.email, "tid": tid},
    )
    if existing.fetchone():
        raise HTTPException(
            status_code=409,
            detail={"code": "DUPLICATE_EMAIL", "message": "Email already exists in this tenant"},
        )

    new_user_id = uuid.uuid4()
    cognito_sub = f"local-{new_user_id}"  # placeholder; real sub comes from Cognito at go-live
    password_hash = _hash_password(body.password) if body.password else None

    await db.execute(
        text(
            """
            INSERT INTO users
                (id, tenant_id, cognito_sub, email, full_name, role,
                 warehouse_id, password_hash, must_reset_password, is_active)
            VALUES (:id, :tid, :sub, :email, :name, :role, :wh, :ph, true, true)
            """
        ),
        {
            "id": str(new_user_id),
            "tid": tid,
            "sub": cognito_sub,
            "email": body.email,
            "name": body.name,
            "role": body.role,
            "wh": str(body.facility_id) if body.facility_id else None,
            "ph": password_hash,
        },
    )

    # Create PRIMARY facility assignment (only when a facility is provided)
    if body.facility_id is not None:
        await db.execute(
            text(
                """
                INSERT INTO user_facility_assignments
                    (tenant_id, user_id, facility_id, assignment_type, role_code,
                     valid_from, created_by, is_active)
                VALUES (:tid, :uid, :fid, 'PRIMARY', :role, now(),
                        :created_by, true)
                """
            ),
            {
                "tid": tid,
                "uid": str(new_user_id),
                "fid": str(body.facility_id),
                "role": body.role,
                "created_by": str(user.user_id) if user else str(new_user_id),
            },
        )

    assignments = await _get_user_assignments(db, str(new_user_id))
    return SuccessResponse(
        data=UserOut(
            id=new_user_id,
            tenant_id=tenant_id,
            email=body.email,
            name=body.name,
            role=body.role,
            primary_facility_id=body.facility_id,
            primary_facility_name=facility.name if facility else None,
            is_active=True,
            assignments=assignments,
        )
    )


# ── Update user ───────────────────────────────────────────────────────────────

@router.patch(
    "/{tenant_id}/users/{user_id}",
    response_model=SuccessResponse[UserOut],
)
@require_permission(PERMISSIONS.USER_MANAGE)
async def update_user(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    body: UserUpdateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[UserOut]:
    tid = str(tenant_id)
    caller_role = getattr(user, "role", "SA")

    row = await db.execute(
        text(
            "SELECT id, email, full_name, role, warehouse_id, is_active "
            "FROM users WHERE id = :uid AND tenant_id = :tid"
        ),
        {"uid": str(user_id), "tid": tid},
    )
    existing = row.fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="User not found")

    new_name = body.full_name if body.full_name is not None else existing.full_name
    new_role = body.role_code if body.role_code is not None else existing.role
    new_wh   = str(body.facility_id) if body.facility_id is not None else str(existing.warehouse_id) if existing.warehouse_id else None

    if body.role_code:
        _check_role_ceiling(caller_role, body.role_code)

    await db.execute(
        text(
            "UPDATE users SET full_name = :name, role = :role, "
            "warehouse_id = :wh, updated_at = now() "
            "WHERE id = :uid AND tenant_id = :tid"
        ),
        {"name": new_name, "role": new_role, "wh": new_wh,
         "uid": str(user_id), "tid": tid},
    )

    fac_name: Optional[str] = None
    if new_wh:
        fac_row = await db.execute(
            text("SELECT name FROM organization_node WHERE id = :id"),
            {"id": new_wh},
        )
        fac = fac_row.fetchone()
        fac_name = fac[0] if fac else None

    assignments = await _get_user_assignments(db, str(user_id))
    return SuccessResponse(
        data=UserOut(
            id=user_id,
            tenant_id=tenant_id,
            email=existing.email,
            name=new_name,
            role=new_role,
            primary_facility_id=uuid.UUID(new_wh) if new_wh else None,
            primary_facility_name=fac_name,
            is_active=existing.is_active,
            assignments=assignments,
        )
    )


# ── Deactivate / reactivate ───────────────────────────────────────────────────

@router.post(
    "/{tenant_id}/users/{user_id}/deactivate",
    response_model=SuccessResponse[dict],
)
@require_permission(PERMISSIONS.USER_MANAGE)
async def deactivate_user(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[dict]:
    # Cannot deactivate yourself
    caller_id = str(user.user_id) if user else None
    if caller_id and caller_id == str(user_id):
        raise HTTPException(
            status_code=422,
            detail={"code": "SELF_DEACTIVATE", "message": "Cannot deactivate your own account"},
        )

    result = await db.execute(
        text(
            "UPDATE users SET is_active = false, updated_at = now() "
            "WHERE id = :uid AND tenant_id = :tid AND is_active = true "
            "RETURNING id"
        ),
        {"uid": str(user_id), "tid": str(tenant_id)},
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="User not found or already inactive")

    # Close all active ACTING/DELEGATE assignments
    await db.execute(
        text(
            "UPDATE user_facility_assignments SET is_active = false "
            "WHERE user_id = :uid AND assignment_type != 'PRIMARY'"
        ),
        {"uid": str(user_id)},
    )
    return SuccessResponse(data={"deactivated": str(user_id)})


@router.post(
    "/{tenant_id}/users/{user_id}/reactivate",
    response_model=SuccessResponse[dict],
)
@require_permission(PERMISSIONS.USER_MANAGE)
async def reactivate_user(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[dict]:
    result = await db.execute(
        text(
            "UPDATE users SET is_active = true, updated_at = now() "
            "WHERE id = :uid AND tenant_id = :tid AND is_active = false "
            "RETURNING id"
        ),
        {"uid": str(user_id), "tid": str(tenant_id)},
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="User not found or already active")
    return SuccessResponse(data={"reactivated": str(user_id)})


# ── Assignments ───────────────────────────────────────────────────────────────

@router.post(
    "/{tenant_id}/users/{user_id}/assignments",
    status_code=201,
    response_model=SuccessResponse[AssignmentOut],
)
@require_permission(PERMISSIONS.USER_MANAGE)
async def create_assignment(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    body: AssignmentCreateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[AssignmentOut]:
    tid = str(tenant_id)
    caller_role = getattr(user, "role", "SA")

    if body.assignment_type not in ("ACTING", "DELEGATE"):
        raise HTTPException(
            status_code=422,
            detail="assignment_type must be ACTING or DELEGATE",
        )

    # Verify target user exists in this tenant
    u_row = await db.execute(
        text("SELECT id, role FROM users WHERE id = :uid AND tenant_id = :tid AND is_active = true"),
        {"uid": str(user_id), "tid": tid},
    )
    target_user = u_row.fetchone()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    # For DELEGATE, role_code is required; enforce ceiling
    effective_role = body.role_code or target_user.role
    if body.role_code:
        _check_role_ceiling(caller_role, body.role_code)

    # Verify facility belongs to this tenant
    fac_row = await db.execute(
        text(
            "SELECT id, name FROM organization_node "
            "WHERE id = :fid AND tenant_id = :tid AND is_active = true"
        ),
        {"fid": str(body.facility_id), "tid": tid},
    )
    facility = fac_row.fetchone()
    if not facility:
        raise HTTPException(status_code=422, detail="facility_id not found in this tenant")

    # Verify target user is within caller's authority scope
    caller_wh = getattr(user, "warehouse_id", None)
    if caller_wh:
        scope = await _get_authority_scope(db, tid, str(caller_wh))
        target_wh_row = await db.execute(
            text("SELECT warehouse_id FROM users WHERE id = :uid"),
            {"uid": str(user_id)},
        )
        t_wh = target_wh_row.fetchone()
        if t_wh and t_wh.warehouse_id and str(t_wh.warehouse_id) not in scope:
            raise HTTPException(
                status_code=403,
                detail={"code": "OUTSIDE_AUTHORITY_SCOPE",
                        "message": "Target user is outside your authority scope"},
            )

    valid_from = body.valid_from or datetime.now(timezone.utc)
    assignment_id = uuid.uuid4()

    await db.execute(
        text(
            """
            INSERT INTO user_facility_assignments
                (id, tenant_id, user_id, facility_id, assignment_type, role_code,
                 valid_from, valid_until, created_by, notes, is_active)
            VALUES (:id, :tid, :uid, :fid, :atype, :role,
                    :vfrom, :vuntil, :created_by, :notes, true)
            """
        ),
        {
            "id": str(assignment_id),
            "tid": tid,
            "uid": str(user_id),
            "fid": str(body.facility_id),
            "atype": body.assignment_type,
            "role": effective_role,
            "vfrom": valid_from,
            "vuntil": body.valid_until,
            "created_by": str(user.user_id) if user else str(user_id),
            "notes": body.notes,
        },
    )

    return SuccessResponse(
        data=AssignmentOut(
            id=assignment_id,
            facility_id=body.facility_id,
            facility_name=facility.name,
            assignment_type=body.assignment_type,
            role_code=effective_role,
            valid_from=valid_from,
            valid_until=body.valid_until,
            notes=body.notes,
            is_active=True,
        )
    )


@router.delete(
    "/{tenant_id}/users/{user_id}/assignments/{assignment_id}",
    response_model=SuccessResponse[dict],
)
@require_permission(PERMISSIONS.USER_MANAGE)
async def deactivate_assignment(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    assignment_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[dict]:
    # Block removal of PRIMARY assignment
    row = await db.execute(
        text(
            "SELECT id, assignment_type FROM user_facility_assignments "
            "WHERE id = :aid AND user_id = :uid AND tenant_id = :tid AND is_active = true"
        ),
        {"aid": str(assignment_id), "uid": str(user_id), "tid": str(tenant_id)},
    )
    assignment = row.fetchone()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    if assignment.assignment_type == "PRIMARY":
        raise HTTPException(
            status_code=422,
            detail={
                "code": "CANNOT_REMOVE_PRIMARY",
                "message": "Cannot remove a PRIMARY facility assignment. "
                           "Deactivate the user instead.",
            },
        )

    await db.execute(
        text(
            "UPDATE user_facility_assignments SET is_active = false "
            "WHERE id = :aid"
        ),
        {"aid": str(assignment_id)},
    )
    return SuccessResponse(data={"deactivated_assignment": str(assignment_id)})
