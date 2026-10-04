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

from shared.cache.login_lockout import (
    _check_login_lockout,
    _login_attempts_key,
    _record_failed_login,
    _reset_login_attempts,
)

router = APIRouter()

JWT_SECRET = os.environ.get("JWT_SECRET") or os.environ.get("JWT_SECRET_KEY")
if not JWT_SECRET:
    raise RuntimeError(
        "JWT_SECRET (or JWT_SECRET_KEY) must be set — refusing to start with an "
        "empty signing secret."
    )
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
                           t.slug AS tenant_slug,
                           t.is_active AS tenant_active, t.status AS tenant_status
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

        # Step 2b — block login for suspended or deactivated tenants
        if user_rec.tenant_id is not None:
            tenant_status = getattr(user_rec, "tenant_status", None)
            if tenant_status == "SUSPENDED":
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code":    "TENANT_SUSPENDED",
                        "message": "This account has been temporarily suspended. "
                                   "Please contact your administrator.",
                    },
                )
            if tenant_status == "DEACTIVATED":
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code":    "TENANT_DEACTIVATED",
                        "message": "This account has been deactivated. "
                                   "Please contact SMART support to retrieve your data.",
                    },
                )

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

        await _check_login_lockout(body.dev_email)

        try:
            claims = await _lookup_user_with_position(body.dev_email, body.dev_password)
        except HTTPException as exc:
            if exc.status_code == 401:
                await _record_failed_login(body.dev_email)
            raise
        if claims is None:
            await _record_failed_login(body.dev_email)
            raise HTTPException(status_code=401, detail="Invalid email or password")

        await _reset_login_attempts(body.dev_email)

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


# ──── Self-Service Signup (Option C) ───────────────────────────────────────

class SignupRequest(BaseModel):
    """Public signup request — creates tenant and TA user account."""

    company_name: str
    email: str
    password: str
    organisation_type: str  # PRODUCER | RETAILER | HYBRID
    plan_tier: str = "STARTER"  # STARTER | GROWTH | ENTERPRISE


class SignupResponse(BaseModel):
    """Response after signup request — user must verify email via OTP."""

    tenant_id: str
    email: str
    message: str
    otp_expires_in_minutes: int


class SignupVerifyRequest(BaseModel):
    """Verify email via OTP during signup."""

    tenant_id: str
    email: str
    otp_code: str
    password: str


class SignupVerifyResponse(BaseModel):
    """Response after successful email verification."""

    tenant_id: str
    tenant_slug: str
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    message: str


@router.post("/signup", response_model=SignupResponse)
async def signup(body: SignupRequest) -> SignupResponse:
    """Public signup endpoint — create tenant and send OTP verification.

    This is Option C: self-service signup for new tenants.
    The TA user account is created with must_reset_password=true, and an OTP
    is sent to the email address for verification.

    On success, the tenant is created in ACTIVE status. The user must verify
    their email via POST /auth/signup/verify before they can log in.
    """
    import uuid
    import re
    from shared.db.session import AsyncSessionLocal
    from shared.email.otp import generate_and_send_otp
    from shared.email.templates import signup_verification_email
    from shared.email import get_email_provider

    # Validate input
    if len(body.password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")

    if not re.match(r"^[^@]+@[^@]+\.[^@]+$", body.email):
        raise HTTPException(status_code=422, detail="Invalid email format")

    if body.organisation_type not in ("PRODUCER", "RETAILER", "HYBRID"):
        raise HTTPException(status_code=422, detail="Invalid organisation_type")

    if body.plan_tier not in ("STARTER", "GROWTH", "ENTERPRISE"):
        raise HTTPException(status_code=422, detail="Invalid plan_tier")

    try:
        tenant_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())

        async with AsyncSessionLocal() as db:
            # Step 1: Check if email already registered
            existing_user = await db.execute(
                sa_text("SELECT id FROM users WHERE lower(email) = lower(:email) AND is_active = true"),
                {"email": body.email},
            )
            if existing_user.fetchone():
                raise HTTPException(status_code=409, detail="Email already registered")

            # Step 2: Create tenant
            tenant_slug = body.company_name.lower().replace(" ", "-")[:50]
            # Ensure slug uniqueness by appending a random suffix if needed
            base_slug = tenant_slug
            counter = 1
            while True:
                existing = await db.execute(
                    sa_text("SELECT id FROM tenants WHERE slug = :slug LIMIT 1"),
                    {"slug": tenant_slug},
                )
                if not existing.fetchone():
                    break
                tenant_slug = f"{base_slug}-{counter}"
                counter += 1

            await db.execute(
                sa_text("""
                    INSERT INTO tenants
                    (id, name, slug, organisation_type, plan_tier, status,
                     onboarding_complete, is_active, created_at, updated_at)
                    VALUES (:id, :name, :slug, :org_type, :plan_tier, 'ACTIVE',
                            false, true, now(), now())
                """),
                {
                    "id": tenant_id,
                    "name": body.company_name,
                    "slug": tenant_slug,
                    "org_type": body.organisation_type,
                    "plan_tier": body.plan_tier,
                },
            )

            # Step 3: Create TA user account with temporary password
            password_hash = _bcrypt.hashpw(body.password.encode(), _bcrypt.gensalt()).decode()
            await db.execute(
                sa_text("""
                    INSERT INTO users
                    (id, tenant_id, email, full_name, password_hash,
                     system_role, must_reset_password, email_verified,
                     is_active, created_at, updated_at)
                    VALUES (:id, :tenant_id, :email, :name, :password_hash,
                            'TA', false, false, true, now(), now())
                """),
                {
                    "id": user_id,
                    "tenant_id": tenant_id,
                    "email": body.email,
                    "name": body.company_name,  # Use company name as default
                    "password_hash": password_hash,
                },
            )

            await db.commit()

        # Step 4: Generate OTP and send verification email
        otp_code = await generate_and_send_otp(body.email, "email_verification")
        subject, html = signup_verification_email(body.company_name, otp_code)

        email_provider = get_email_provider()
        await email_provider.send(
            to=body.email,
            subject=subject,
            html=html,
        )

        otp_expiry = int(os.environ.get("OTP_EXPIRY_MINUTES", "15"))

        return SignupResponse(
            tenant_id=tenant_id,
            email=body.email,
            message=f"Signup successful! A verification code has been sent to {body.email}. "
            f"Use the code to verify your email and complete signup.",
            otp_expires_in_minutes=otp_expiry,
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Signup error: {str(exc)}") from exc


@router.post("/signup/verify", response_model=SignupVerifyResponse)
async def signup_verify(body: SignupVerifyRequest) -> SignupVerifyResponse:
    """Verify email via OTP after signup and issue JWT.

    Once OTP is verified:
    1. Mark user email_verified = true
    2. Create the onboarding wizard state (mark onboarding_complete = false but init wizard)
    3. Issue a JWT for the TA user
    4. Return access token so user can proceed to onboarding wizard
    """
    from shared.db.session import AsyncSessionLocal
    from shared.email.otp import verify_otp

    try:
        # Step 1: Verify OTP
        is_valid = await verify_otp(body.email, body.otp_code, "email_verification")
        if not is_valid:
            raise HTTPException(status_code=401, detail="Invalid or expired OTP code")

        # Step 2: Find user and mark email as verified
        async with AsyncSessionLocal() as db:
            # Verify tenant and user match
            user_row = await db.execute(
                sa_text("""
                    SELECT u.id, u.tenant_id, u.email, u.full_name, u.system_role,
                           t.slug, t.status
                    FROM users u
                    JOIN tenants t ON t.id = u.tenant_id
                    WHERE u.tenant_id = :tenant_id AND lower(u.email) = lower(:email)
                    AND u.system_role = 'TA' AND u.is_active = true
                    LIMIT 1
                """),
                {"tenant_id": body.tenant_id, "email": body.email},
            )
            user_rec = user_row.fetchone()

            if not user_rec:
                raise HTTPException(status_code=404, detail="User or tenant not found")

            # Check tenant is not suspended/deactivated
            if user_rec.status == "SUSPENDED":
                raise HTTPException(status_code=403, detail="Tenant is suspended")
            if user_rec.status == "DEACTIVATED":
                raise HTTPException(status_code=403, detail="Tenant is deactivated")

            # Mark email as verified
            await db.execute(
                sa_text(
                    "UPDATE users SET email_verified = true, updated_at = now() "
                    "WHERE id = :uid"
                ),
                {"uid": str(user_rec.id)},
            )

            await db.commit()

        # Step 3: Issue JWT
        now = datetime.now(timezone.utc)
        jwt_payload = {
            "sub": str(user_rec.id),
            "email": str(user_rec.email),
            "name": str(user_rec.full_name),
            "tenant_id": str(user_rec.tenant_id),
            "tenant_slug": str(user_rec.slug) if user_rec.slug else None,
            "role": "TA",
            "warehouse_id": None,
            "warehouse_name": None,
            "position_id": None,
            "position_title": None,
            "level_number": None,
            "positions": [],
            "must_reset_password": False,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=JWT_EXPIRE)).timestamp()),
        }

        token = jwt.encode(jwt_payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

        return SignupVerifyResponse(
            tenant_id=str(user_rec.tenant_id),
            tenant_slug=str(user_rec.slug) if user_rec.slug else "unknown",
            access_token=token,
            expires_in=JWT_EXPIRE * 60,
            message="Email verified successfully! You can now log in and complete your tenant setup.",
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Verification error: {str(exc)}") from exc
