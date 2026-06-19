"""Auth-service token endpoint.

Session 2: JWT claims are now derived from the user's PRIMARY active position
in personnel_positions → positions → organization_node.  The old DEV_USERS
hardcoded dict (demo tenants) has been removed; role and warehouse_id are no
longer columns on the users table.

SA accounts (tenant_id IS NULL) bypass position lookup and receive a
hardcoded SA claim set.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt as _bcrypt
from fastapi import APIRouter, HTTPException
from jose import jwt
from pydantic import BaseModel

router = APIRouter()

JWT_SECRET    = os.environ.get("JWT_SECRET", os.environ.get("JWT_SECRET_KEY", ""))
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
JWT_EXPIRE    = int(os.environ.get("JWT_EXPIRE_MINUTES", "60"))
ENVIRONMENT   = os.environ.get("ENVIRONMENT", "")


async def _lookup_user_with_position(
    email: str,
    password: Optional[str] = None,
) -> Optional[dict]:
    """Find user by email and derive JWT claims from their primary active position.

    Returns a claims dict ready to embed in the JWT, or None if not found.
    Raises HTTP 401 on password mismatch.
    Raises HTTP 403 if user exists but has no active PRIMARY position assigned.
    SA users (tenant_id IS NULL) bypass position lookup.
    """
    try:
        from shared.db.session import AsyncSessionLocal
        from sqlalchemy import text as sa_text

        async with AsyncSessionLocal() as db:
            # Step 1 — find user by email WITHOUT is_active filter so we can
            # distinguish "unknown email" from "deactivated account" and return
            # the same 401 for both (no information leak).
            user_row = await db.execute(
                sa_text("""
                    SELECT u.id, u.email, u.full_name, u.tenant_id,
                           u.password_hash, u.must_reset_password,
                           u.system_role, u.is_active,
                           t.slug AS tenant_slug
                    FROM   users u
                    LEFT JOIN tenants t ON t.id = u.tenant_id
                    WHERE  lower(u.email) = lower(:email)
                    LIMIT  1
                """),
                {"email": email},
            )
            user_rec = user_row.fetchone()

        if user_rec is None:
            return None  # caller raises 401

        # Step 2 — reject deactivated accounts with the same 401 as "not found"
        # to avoid leaking whether an email address is registered.
        if not bool(user_rec.is_active):
            raise HTTPException(status_code=401, detail="Invalid email or password")

        # Verify password when provided
        if password is not None:
            stored = user_rec.password_hash
            if stored is None or not _bcrypt.checkpw(password.encode(), stored.encode()):
                raise HTTPException(status_code=401, detail="Invalid password")

        # Tenant-wide direct roles — system_role set, no position required.
        # Must mirror personnel_v2.py's VALID_DIRECT_SYSTEM_ROLES (TA/AU/LM).
        # SA is intentionally excluded here — SA accounts never populate
        # system_role; they are identified by tenant_id IS NULL (handled below).
        _DIRECT_ROLE_TITLES = {
            "TA": "Tenant Administrator",
            "AU": "Auditor",
            "LM": "Logistics Manager",
        }
        direct_role = getattr(user_rec, "system_role", None)
        if direct_role in _DIRECT_ROLE_TITLES:
            return {
                "sub":                  str(user_rec.id),
                "email":                str(user_rec.email),
                "name":                 str(user_rec.full_name),
                "tenant_id":            str(user_rec.tenant_id),
                "tenant_slug":          str(user_rec.tenant_slug) if user_rec.tenant_slug else None,
                "role":                 direct_role,
                "warehouse_id":         None,
                "warehouse_name":       None,
                "position_id":          None,
                "position_title":       _DIRECT_ROLE_TITLES[direct_role],
                "level_number":         1,
                "positions":            [],
                "must_reset_password":  bool(user_rec.must_reset_password),
            }

        # SA — no tenant, no position; return hardcoded SA claims
        if user_rec.tenant_id is None:
            return {
                "sub":                  str(user_rec.id),
                "email":                str(user_rec.email),
                "name":                 str(user_rec.full_name),
                "tenant_id":            None,
                "tenant_slug":          None,
                "role":                 "SA",
                "warehouse_id":         None,
                "warehouse_name":       None,
                "position_id":          None,
                "position_title":       None,
                "level_number":         None,
                "positions":            [],
                "must_reset_password":  bool(user_rec.must_reset_password),
            }

        async with AsyncSessionLocal() as db:
            # Step 2 — primary active position
            primary_row = await db.execute(
                sa_text("""
                    SELECT pp.id                   AS pp_id,
                           p.role_code,
                           p.node_id,
                           p.title,
                           n.name                 AS node_name,
                           n.hierarchy_level,
                           tc.level_name
                    FROM   personnel_positions pp
                    JOIN   positions           p  ON pp.position_id  = p.id
                    JOIN   organization_node   n  ON p.node_id       = n.id
                    LEFT JOIN tenant_hierarchy_config tc
                           ON  tc.tenant_id    = p.tenant_id
                           AND tc.level_number = n.hierarchy_level
                    WHERE  pp.user_id          = :uid
                    AND    pp.assignment_type  = 'PRIMARY'
                    AND    pp.is_active        = true
                    AND    (pp.valid_until IS NULL OR pp.valid_until >= CURRENT_DATE)
                    LIMIT  1
                """),
                {"uid": str(user_rec.id)},
            )
            primary_rec = primary_row.fetchone()

            if primary_rec is None:
                # TA users may not have a position — already handled above via system_role.
                #
                # For non-TA users without a position AND must_reset_password=true:
                # issue a PENDING_SETUP JWT so they can reach the change-password page
                # before their position is assigned.  This prevents the catch-22 where
                # a new user with a temp password can never log in to change it.
                if bool(user_rec.must_reset_password):
                    return {
                        "sub":                 str(user_rec.id),
                        "email":               str(user_rec.email),
                        "name":                str(user_rec.full_name),
                        "tenant_id":           str(user_rec.tenant_id),
                        "tenant_slug":         str(user_rec.tenant_slug) if user_rec.tenant_slug else None,
                        "role":                "PENDING_SETUP",
                        "warehouse_id":        None,
                        "warehouse_name":      None,
                        "position_id":         None,
                        "position_title":      None,
                        "level_number":        None,
                        "positions":           [],
                        "must_reset_password": True,
                    }
                # User has no position and no pending password reset → hard block.
                raise HTTPException(
                    status_code=403,
                    detail="No active position assigned. Contact your administrator.",
                )

            # Step 3 — all active positions (PRIMARY + ACTING + DELEGATE)
            all_rows = await db.execute(
                sa_text("""
                    SELECT pp.id                   AS pp_id,
                           pp.assignment_type,
                           p.role_code,
                           p.node_id,
                           p.title,
                           n.name                 AS node_name,
                           n.hierarchy_level
                    FROM   personnel_positions pp
                    JOIN   positions           p  ON pp.position_id = p.id
                    JOIN   organization_node   n  ON p.node_id      = n.id
                    WHERE  pp.user_id    = :uid
                    AND    pp.is_active  = true
                    AND    (pp.valid_until IS NULL OR pp.valid_until >= CURRENT_DATE)
                """),
                {"uid": str(user_rec.id)},
            )
            all_positions = all_rows.fetchall()

        return {
            "sub":                  str(user_rec.id),
            "email":                str(user_rec.email),
            "name":                 str(user_rec.full_name),
            "tenant_id":            str(user_rec.tenant_id),
            "tenant_slug":          str(user_rec.tenant_slug) if user_rec.tenant_slug else None,
            "role":                 str(primary_rec.role_code),
            "warehouse_id":         str(primary_rec.node_id),
            "warehouse_name":       str(primary_rec.node_name),
            "position_id":          str(primary_rec.pp_id),
            "position_title":       str(primary_rec.title),
            "level_number":         int(primary_rec.hierarchy_level),
            "positions": [
                {
                    "position_id":      str(pos.pp_id),
                    "role_code":        str(pos.role_code),
                    "node_id":          str(pos.node_id),
                    "node_name":        str(pos.node_name),
                    "level_number":     int(pos.hierarchy_level),
                    "assignment_type":  str(pos.assignment_type),
                }
                for pos in all_positions
            ],
            "must_reset_password":  bool(user_rec.must_reset_password),
        }

    except HTTPException:
        raise
    except Exception:
        return None


class TokenRequest(BaseModel):
    cognito_token:  str | None = None
    demo_sub:       str | None = None
    demo_role:      str | None = None
    demo_tenant_id: str | None = None
    demo_warehouse_id: str | None = None
    dev_email:      str | None = None
    dev_password:   str | None = None


class TokenResponse(BaseModel):
    access_token:       str
    token_type:         str  = "bearer"
    expires_in:         int
    tenant_slug:        str | None = None
    must_reset_password: bool = False


@router.post("/token", response_model=TokenResponse)
async def exchange_token(body: TokenRequest) -> TokenResponse:
    """Issue a SMART JWT.

    Path 1 — dev_email (ENVIRONMENT=local only):
      Looks up user from DB, queries primary position, builds position-aware JWT.
      SA users get hardcoded SA claims (no position required).

    Path 2/3 — cognito_token (demo overrides or production Cognito):
      Not yet migrated to position model; passes demo_* claims through.
    """
    now = datetime.now(timezone.utc)
    tenant_slug:         str | None = None
    must_reset_password: bool       = False

    # ── Path 1: local dev bypass ───────────────────────────────────────────
    if body.dev_email is not None:
        if ENVIRONMENT != "local":
            raise HTTPException(
                status_code=403,
                detail="dev_email bypass is only available when ENVIRONMENT=local",
            )
        claims = await _lookup_user_with_position(body.dev_email, body.dev_password)
        if claims is None:
            raise HTTPException(status_code=401, detail="Invalid email or password")

        tenant_slug          = claims.get("tenant_slug")
        must_reset_password  = bool(claims.get("must_reset_password", False))

        payload: dict = {
            "sub":            claims["sub"],
            "email":          claims["email"],
            "name":           claims["name"],
            "tenant_id":      claims["tenant_id"],
            "role":           claims["role"],
            "warehouse_id":   claims["warehouse_id"],
            "warehouse_name": claims["warehouse_name"],
            "position_id":    claims["position_id"],
            "position_title": claims["position_title"],
            "level_number":   claims["level_number"],
            "positions":      claims["positions"],
            "iat":            int(now.timestamp()),
            "exp":            int((now + timedelta(minutes=JWT_EXPIRE)).timestamp()),
        }

    # ── Path 2/3: cognito_token ──────��─────────────────────────────────────
    elif body.cognito_token is not None:
        sub          = body.demo_sub          or "00000000-0000-0000-0000-000000000001"
        role         = body.demo_role         or "WM"
        tenant_id    = body.demo_tenant_id    or "10000000-0000-0000-0000-000000000001"
        warehouse_id = body.demo_warehouse_id

        payload = {
            "sub":            sub,
            "role":           role,
            "tenant_id":      tenant_id,
            "warehouse_id":   warehouse_id,
            "warehouse_name": None,
            "position_id":    None,
            "position_title": None,
            "level_number":   None,
            "positions":      [],
            "iat":            int(now.timestamp()),
            "exp":            int((now + timedelta(minutes=JWT_EXPIRE)).timestamp()),
        }
    else:
        raise HTTPException(
            status_code=422,
            detail="Provide dev_email (local only) or cognito_token",
        )

    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return TokenResponse(
        access_token=token,
        expires_in=JWT_EXPIRE * 60,
        tenant_slug=tenant_slug,
        must_reset_password=must_reset_password,
    )


@router.post("/refresh")
async def refresh_token() -> dict:
    return {"message": "use Cognito refresh flow"}


class ChangePasswordByIdRequest(BaseModel):
    user_id:          str
    current_password: Optional[str] = None   # optional for must_reset users
    new_password:     str


@router.patch("/password/{user_id}", response_model=dict)
async def change_password_by_id(user_id: str, body: ChangePasswordByIdRequest) -> dict:
    """Change password for a user identified by user_id.

    For users with must_reset_password=true (PENDING_SETUP role — new accounts
    awaiting position assignment), current_password may be omitted because the
    user may have been given a temporary password they cannot verify without
    first logging in.  All other active users must supply current_password.
    """
    if ENVIRONMENT != "local":
        raise HTTPException(status_code=403, detail="Only available when ENVIRONMENT=local")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=422, detail="New password must be at least 8 characters")

    try:
        from shared.db.session import AsyncSessionLocal
        from sqlalchemy import text as sa_text
        async with AsyncSessionLocal() as db:
            row = (await db.execute(
                sa_text(
                    "SELECT id, password_hash, must_reset_password "
                    "FROM users WHERE id = :uid AND is_active = true"
                ),
                {"uid": user_id},
            )).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="User not found")

            must_reset = bool(row.must_reset_password)

            if not must_reset:
                # Standard path: current_password is required.
                if not body.current_password:
                    raise HTTPException(status_code=422, detail="Current password is required")
                if row.password_hash is None:
                    raise HTTPException(
                        status_code=401,
                        detail="No password set for this account — contact your administrator",
                    )
                if not _bcrypt.checkpw(
                    body.current_password.encode(), row.password_hash.encode()
                ):
                    raise HTTPException(status_code=401, detail="Current password is incorrect")
            elif body.current_password:
                # must_reset=true but caller supplied current_password: validate it.
                # (Allows users who know their temp password to confirm it.)
                if row.password_hash is not None and not _bcrypt.checkpw(
                    body.current_password.encode(), row.password_hash.encode()
                ):
                    raise HTTPException(status_code=401, detail="Current password is incorrect")
            # else: must_reset=true, no current_password → skip verification (PENDING_SETUP path)

            new_hash = _bcrypt.hashpw(body.new_password.encode(), _bcrypt.gensalt()).decode()
            await db.execute(
                sa_text(
                    "UPDATE users SET password_hash = :ph, must_reset_password = false,"
                    " updated_at = now() WHERE id = :uid"
                ),
                {"ph": new_hash, "uid": user_id},
            )
            await db.commit()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

    return {"success": True, "message": "Password updated successfully"}
