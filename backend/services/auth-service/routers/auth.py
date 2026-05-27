import os
from datetime import datetime, timedelta, timezone

import bcrypt as _bcrypt
from fastapi import APIRouter, HTTPException
from jose import jwt
from pydantic import BaseModel

router = APIRouter()

JWT_SECRET    = os.environ.get("JWT_SECRET", os.environ.get("JWT_SECRET_KEY", ""))
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
JWT_EXPIRE    = int(os.environ.get("JWT_EXPIRE_MINUTES", "60"))
ENVIRONMENT   = os.environ.get("ENVIRONMENT", "")

# ── Local-dev user registry ────────────────────────────────────────────────────
# Maps every seeded demo email → fixed JWT claims (UUIDs match seed_demo_data.py).
# Only reachable when ENVIRONMENT=local — rejected with 403 in all other envs.
# Add entries here whenever a new seed user is added to seed_demo_data.py.
DEV_USERS: dict[str, dict[str, str | None]] = {
    # ── System Admin ──────────────────────────────────────────────────────────
    "smartadmin@smart-inventory.com": {
        "sub": "00000001-0a00-0000-0000-000000000001", "role": "SA",
        "tenant_id": None, "warehouse_id": None,
    },
    # ── Addis Water ───────────────────────────────────────────────────────────
    "admin@addis-water.com": {
        "sub": "00000001-a001-0000-0000-000000000001", "role": "TA",
        "tenant_id": "10000001-0000-0000-0000-000000000001", "warehouse_id": None,
    },
    "production@addis-water.com": {
        "sub": "00000001-a002-0000-0000-000000000001", "role": "NM",
        "tenant_id": "10000001-0000-0000-0000-000000000001",
        "warehouse_id": "20000001-a000-0000-0000-000000000001",
    },
    "north.wm@addis-water.com": {
        "sub": "00000001-a003-0000-0000-000000000001", "role": "WM",
        "tenant_id": "10000001-0000-0000-0000-000000000001",
        "warehouse_id": "20000001-a000-0000-0000-000000000002",
    },
    "northsub.wm@addis-water.com": {
        "sub": "00000001-a004-0000-0000-000000000001", "role": "WM",
        "tenant_id": "10000001-0000-0000-0000-000000000001",
        "warehouse_id": "20000001-a000-0000-0000-000000000003",
    },
    "south.wm@addis-water.com": {
        "sub": "00000001-a005-0000-0000-000000000001", "role": "WM",
        "tenant_id": "10000001-0000-0000-0000-000000000001",
        "warehouse_id": "20000001-a000-0000-0000-000000000004",
    },
    "east.wm@addis-water.com": {
        "sub": "00000001-a006-0000-0000-000000000001", "role": "WM",
        "tenant_id": "10000001-0000-0000-0000-000000000001",
        "warehouse_id": "20000001-a000-0000-0000-000000000005",
    },
    "west.wm@addis-water.com": {
        "sub": "00000001-a007-0000-0000-000000000001", "role": "WM",
        "tenant_id": "10000001-0000-0000-0000-000000000001",
        "warehouse_id": "20000001-a000-0000-0000-000000000006",
    },
    # ── Muger Cement ──────────────────────────────────────────────────────────
    "admin@muger-cement.com": {
        "sub": "00000002-0c01-0000-0000-000000000001", "role": "TA",
        "tenant_id": "10000002-0000-0000-0000-000000000001", "warehouse_id": None,
    },
    "harar.pm@muger-cement.com": {
        "sub": "00000002-0c02-0000-0000-000000000001", "role": "NM",
        "tenant_id": "10000002-0000-0000-0000-000000000001",
        "warehouse_id": "20000002-0c00-0000-0000-000000000001",
    },
    "ambo.pm@muger-cement.com": {
        "sub": "00000002-0c03-0000-0000-000000000001", "role": "NM",
        "tenant_id": "10000002-0000-0000-0000-000000000001",
        "warehouse_id": "20000002-0c00-0000-0000-000000000002",
    },
    "kombolcha.wm@muger-cement.com": {
        "sub": "00000002-0c04-0000-0000-000000000001", "role": "WM",
        "tenant_id": "10000002-0000-0000-0000-000000000001",
        "warehouse_id": "20000002-0c00-0000-0000-000000000003",
    },
    "mekele.wm@muger-cement.com": {
        "sub": "00000002-0c05-0000-0000-000000000001", "role": "WM",
        "tenant_id": "10000002-0000-0000-0000-000000000001",
        "warehouse_id": "20000002-0c00-0000-0000-000000000004",
    },
    "diredawa.wm@muger-cement.com": {
        "sub": "00000002-0c06-0000-0000-000000000001", "role": "WM",
        "tenant_id": "10000002-0000-0000-0000-000000000001",
        "warehouse_id": "20000002-0c00-0000-0000-000000000005",
    },
    "hawassa.wm@muger-cement.com": {
        "sub": "00000002-0c07-0000-0000-000000000001", "role": "WM",
        "tenant_id": "10000002-0000-0000-0000-000000000001",
        "warehouse_id": "20000002-0c00-0000-0000-000000000006",
    },
}


async def _lookup_user_in_db(email: str, password: str | None = None) -> dict | None:
    """Query the users table for a dynamically-created user (not in DEV_USERS).
    Returns JWT claim fields or None if not found / DB unavailable.
    When password is provided, verifies bcrypt hash — raises 401 on mismatch.
    Only called in ENVIRONMENT=local dev_email path.
    """
    try:
        from shared.db.session import AsyncSessionLocal
        from sqlalchemy import text as sa_text
        async with AsyncSessionLocal() as db:
            row = await db.execute(
                sa_text("""
                    SELECT u.id, u.role, u.tenant_id, u.password_hash, ufa.facility_id,
                           t.slug AS tenant_slug,
                           COALESCE(u.must_reset_password, false) AS must_reset_password
                    FROM users u
                    LEFT JOIN user_facility_assignments ufa
                        ON ufa.user_id = u.id
                        AND ufa.assignment_type = 'PRIMARY'
                        AND ufa.is_active = true
                    LEFT JOIN tenants t ON t.id = u.tenant_id
                    WHERE lower(u.email) = lower(:email) AND u.is_active = true
                    LIMIT 1
                """),
                {"email": email},
            )
            rec = row.fetchone()
        if rec is None:
            return None
        # Verify password when one is provided and the user has a hash stored
        if password is not None:
            stored_hash = rec.password_hash
            if stored_hash is None or not _bcrypt.checkpw(
                password.encode(), stored_hash.encode()
            ):
                raise HTTPException(status_code=401, detail="Invalid password")
        return {
            "sub":                 str(rec.id),
            "role":                str(rec.role),
            "tenant_id":           str(rec.tenant_id) if rec.tenant_id else None,
            "tenant_slug":         str(rec.tenant_slug) if rec.tenant_slug else None,
            "warehouse_id":        str(rec.facility_id) if rec.facility_id else None,
            "must_reset_password": bool(rec.must_reset_password),
        }
    except HTTPException:
        raise
    except Exception:
        return None


class TokenRequest(BaseModel):
    # Production path: Cognito IdToken (required in non-local envs).
    # Optional here so dev_email can be used alone in local mode.
    cognito_token:     str | None = None
    # Demo-only overrides — used with cognito_token="demo" from the frontend.
    # When present these take priority over any Cognito payload.
    demo_sub:          str | None = None
    demo_role:         str | None = None
    demo_tenant_id:    str | None = None
    demo_warehouse_id: str | None = None
    # Local-dev shortcut: pass an email and get a fully-scoped JWT without Cognito.
    # Only accepted when ENVIRONMENT=local. Rejected with 403 in all other envs.
    dev_email:         str | None = None
    # Optional password for API-created users (bcrypt verified). Not required for
    # hardcoded DEV_USERS (demo accounts). Ignored in Cognito paths.
    dev_password:      str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    tenant_slug: str | None = None
    must_reset_password: bool = False


@router.post("/token", response_model=TokenResponse)
async def exchange_token(body: TokenRequest) -> TokenResponse:
    """Issue a SMART JWT.

    Three paths:
      1. dev_email (ENVIRONMENT=local only) — looks up claims from DEV_USERS dict.
      2. cognito_token + demo_* overrides — demo frontend path.
      3. cognito_token only — production Cognito validation (not yet implemented).
    """
    now = datetime.now(timezone.utc)
    tenant_slug: str | None = None
    must_reset_password: bool = False

    # ── Path 1: local dev bypass via dev_email ─────────────────────────────
    if body.dev_email is not None:
        if ENVIRONMENT != "local":
            raise HTTPException(
                status_code=403,
                detail="dev_email bypass is only available when ENVIRONMENT=local",
            )
        entry = DEV_USERS.get(body.dev_email.lower())
        if entry is not None:
            sub          = str(entry["sub"])
            role         = str(entry["role"])
            tenant_id    = entry["tenant_id"]
            warehouse_id = entry["warehouse_id"]
        else:
            # Fallback: look up dynamically-created users in the database
            db_user = await _lookup_user_in_db(body.dev_email, body.dev_password)
            if db_user is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"dev_email not found: {body.dev_email!r}",
                )
            sub                  = db_user["sub"]
            role                 = db_user["role"]
            tenant_id            = db_user["tenant_id"]
            tenant_slug          = db_user.get("tenant_slug")
            warehouse_id         = db_user["warehouse_id"]
            must_reset_password  = bool(db_user.get("must_reset_password", False))

    # ── Path 2 / 3: cognito_token (+ optional demo_* overrides) ───────────
    elif body.cognito_token is not None:
        # Production: validate body.cognito_token against Cognito JWKS here.
        # Demo/local: demo_* fields carry the claims directly.
        sub          = body.demo_sub          or "00000000-0000-0000-0000-000000000001"
        role         = body.demo_role         or "WM"
        tenant_id    = body.demo_tenant_id    or "10000000-0000-0000-0000-000000000001"
        warehouse_id = body.demo_warehouse_id  # None is valid for NM/TA

    else:
        raise HTTPException(
            status_code=422,
            detail="Provide dev_email (local only) or cognito_token",
        )

    payload: dict[str, object] = {
        "sub":          sub,
        "role":         role,
        "tenant_id":    tenant_id,
        "region_id":    None,
        "warehouse_id": warehouse_id,
        "iat":          int(now.timestamp()),
        "exp":          int((now + timedelta(minutes=JWT_EXPIRE)).timestamp()),
    }
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


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.patch("/password", response_model=dict)
async def change_password(body: ChangePasswordRequest) -> dict:
    """Change password for an authenticated user and clear must_reset_password flag.

    Requires a valid SMART JWT in the Authorization header.
    Only available in ENVIRONMENT=local (Cognito handles this in production).
    """
    if ENVIRONMENT != "local":
        raise HTTPException(
            status_code=403,
            detail="Password change via this endpoint is only available when ENVIRONMENT=local",
        )
    if len(body.new_password) < 8:
        raise HTTPException(status_code=422, detail="New password must be at least 8 characters")

    try:
        from fastapi import Request
        from jose import JWTError, jwt as _jwt
    except ImportError:
        raise HTTPException(status_code=500, detail="JWT library unavailable")

    # This endpoint is called with a Bearer token — we need the request object.
    # Since we're not using Depends(get_current_user) here (auth-service doesn't have
    # that dependency), we use a manual approach via a secondary function below.
    raise HTTPException(
        status_code=501,
        detail="Use PATCH /api/v1/auth/password/{user_id} with user_id from JWT sub claim",
    )


class ChangePasswordByIdRequest(BaseModel):
    user_id: str
    current_password: str
    new_password: str


@router.patch("/password/{user_id}", response_model=dict)
async def change_password_by_id(user_id: str, body: ChangePasswordByIdRequest) -> dict:
    """Change password for a user identified by user_id and clear must_reset_password.

    Only available in ENVIRONMENT=local.
    """
    if ENVIRONMENT != "local":
        raise HTTPException(
            status_code=403,
            detail="Password change via this endpoint is only available when ENVIRONMENT=local",
        )
    if len(body.new_password) < 8:
        raise HTTPException(status_code=422, detail="New password must be at least 8 characters")

    try:
        from shared.db.session import AsyncSessionLocal
        from sqlalchemy import text as sa_text
        async with AsyncSessionLocal() as db:
            row = await db.execute(
                sa_text("SELECT id, password_hash FROM users WHERE id = :uid AND is_active = true"),
                {"uid": user_id},
            )
            rec = row.fetchone()
            if rec is None:
                raise HTTPException(status_code=404, detail="User not found")

            if rec.password_hash is None or not _bcrypt.checkpw(
                body.current_password.encode(), rec.password_hash.encode()
            ):
                raise HTTPException(status_code=401, detail="Current password is incorrect")

            new_hash = _bcrypt.hashpw(body.new_password.encode(), _bcrypt.gensalt()).decode()
            await db.execute(
                sa_text(
                    "UPDATE users SET password_hash = :ph, must_reset_password = false, "
                    "updated_at = now() WHERE id = :uid"
                ),
                {"ph": new_hash, "uid": user_id},
            )
            await db.commit()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

    return {"success": True, "message": "Password updated successfully"}
