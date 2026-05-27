import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from jose import jwt
from passlib.context import CryptContext
from pydantic import BaseModel

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

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
                    SELECT u.id, u.role, u.tenant_id, u.password_hash, ufa.facility_id
                    FROM users u
                    LEFT JOIN user_facility_assignments ufa
                        ON ufa.user_id = u.id
                        AND ufa.assignment_type = 'PRIMARY'
                        AND ufa.is_active = true
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
            if stored_hash is None or not _pwd_ctx.verify(password, stored_hash):
                raise HTTPException(status_code=401, detail="Invalid password")
        return {
            "sub":          str(rec.id),
            "role":         str(rec.role),
            "tenant_id":    str(rec.tenant_id) if rec.tenant_id else None,
            "warehouse_id": str(rec.facility_id) if rec.facility_id else None,
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


@router.post("/token", response_model=TokenResponse)
async def exchange_token(body: TokenRequest) -> TokenResponse:
    """Issue a SMART JWT.

    Three paths:
      1. dev_email (ENVIRONMENT=local only) — looks up claims from DEV_USERS dict.
      2. cognito_token + demo_* overrides — demo frontend path.
      3. cognito_token only — production Cognito validation (not yet implemented).
    """
    now = datetime.now(timezone.utc)

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
            sub          = db_user["sub"]
            role         = db_user["role"]
            tenant_id    = db_user["tenant_id"]
            warehouse_id = db_user["warehouse_id"]

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
    return TokenResponse(access_token=token, expires_in=JWT_EXPIRE * 60)


@router.post("/refresh")
async def refresh_token() -> dict:
    return {"message": "use Cognito refresh flow"}
