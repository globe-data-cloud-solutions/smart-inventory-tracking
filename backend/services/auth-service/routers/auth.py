"""Auth-service token endpoint.

Session 2: JWT claims are now derived from the user's PRIMARY active position
in personnel_positions → positions → organization_node.  The old DEV_USERS
hardcoded dict (demo tenants) has been removed; role and warehouse_id are no
longer columns on the users table.

SA accounts (tenant_id IS NULL) bypass position lookup and receive a
hardcoded SA claim set.
"""
import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt as _bcrypt
from fastapi import APIRouter, HTTPException, Request
from jose import JWTError, jwt
from pydantic import BaseModel

from shared.auth.email_verification import (
    consume_verification_token,
    issue_verification_token,
    send_verification_email,
    verification_required,
)
from shared.auth.password_reset import (
    consume_reset_token,
    issue_reset_token,
    send_reset_email,
)
from shared.cache.login_lockout import (
    _check_login_lockout,
    _login_attempts_key,
    _record_failed_login,
    _reset_login_attempts,
)
from shared.cache.rate_limit import client_ip, hit_bucket as rate_limit_hit
from shared.cache.token_revocation import revoke_user_tokens
from shared.utils.terms import get_terms_version

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
        from shared.db.rls import set_rls_context
        from shared.db.session import AsyncSessionLocal
        from sqlalchemy import text as sa_text

        async with AsyncSessionLocal() as db:
            # Step 1 — find user by email WITHOUT is_active filter so we can
            # distinguish "unknown email" from "deactivated account" and return
            # the same 401 for both (no information leak).
            # No tenant context exists before login, so users is read through
            # the SECURITY DEFINER auth_user_by_email (migration 091, D6).
            user_row = await db.execute(
                sa_text("SELECT * FROM auth_user_by_email(:email)"),
                {"email": email},
            )
            user_rec = user_row.fetchone()

        if user_rec is None:
            return None  # caller raises 401

        # Step 2 — reject deactivated accounts with the same 401 as "not found"
        # to avoid leaking whether an email address is registered.
        if not bool(user_rec.is_active):
            raise HTTPException(status_code=401, detail="Invalid email or password")

        # Step 2b — verify password BEFORE the tenant status checks below, so a
        # SUSPENDED/DEACTIVATED 403 (which confirms the tenant's existence and
        # state) is only ever returned to a caller who has already proven they
        # know the password. When password is None (dev_email local path),
        # there is nothing to verify here — unchanged behaviour.
        if password is not None:
            stored = user_rec.password_hash
            if stored is None or not _bcrypt.checkpw(password.encode(), stored.encode()):
                raise HTTPException(status_code=401, detail="Invalid password")

        # Step 2c — block login for suspended or deactivated tenants
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

        # Account-owner terms re-acceptance gate — only the account owner is
        # ever asked, and only when they have a tenant. No acceptance row at
        # all (e.g. an SA-created tenant, which never runs public_signup)
        # counts as required, same as a stale version.
        terms_acceptance_required = False
        if user_rec.tenant_id is not None and bool(user_rec.is_account_owner):
            async with AsyncSessionLocal() as db:
                await set_rls_context(db, str(user_rec.tenant_id), str(user_rec.id))
                terms_row = await db.execute(
                    sa_text(
                        "SELECT terms_version FROM terms_acceptances "
                        "WHERE tenant_id = :tid ORDER BY accepted_at DESC LIMIT 1"
                    ),
                    {"tid": str(user_rec.tenant_id)},
                )
                latest_terms = terms_row.fetchone()
            terms_acceptance_required = (
                latest_terms is None or latest_terms.terms_version != get_terms_version()
            )

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
                "email_verified_at":    user_rec.email_verified_at,
                "terms_acceptance_required": terms_acceptance_required,
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
                "email_verified_at":    user_rec.email_verified_at,
                "terms_acceptance_required": False,
            }

        async with AsyncSessionLocal() as db:
            await set_rls_context(db, str(user_rec.tenant_id), str(user_rec.id))
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
                        "email_verified_at":   user_rec.email_verified_at,
                        "terms_acceptance_required": terms_acceptance_required,
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
            "email_verified_at":    user_rec.email_verified_at,
            "terms_acceptance_required": terms_acceptance_required,
        }

    except HTTPException:
        raise
    except Exception:
        return None


class TokenRequest(BaseModel):
    email:          str | None = None
    password:       str | None = None
    dev_email:      str | None = None
    dev_password:   str | None = None


class TokenResponse(BaseModel):
    access_token:       str
    token_type:         str  = "bearer"
    expires_in:         int
    tenant_slug:        str | None = None
    must_reset_password: bool = False
    terms_acceptance_required: bool = False


async def _password_login(email: str, password: Optional[str]) -> dict:
    """Shared login flow used by both the email/password and dev_email paths:
    lockout check, DB lookup + password verification, failed-attempt
    tracking, success reset, and the email-verification gate.

    Raises HTTPException on failure (401 from _lookup_user_with_position,
    429 from the lockout check, 403 EMAIL_NOT_VERIFIED). Returns the JWT
    claims dict on success.
    """
    await _check_login_lockout(email)

    try:
        claims = await _lookup_user_with_position(email, password)
    except HTTPException as exc:
        if exc.status_code == 401:
            await _record_failed_login(email)
        raise
    if claims is None:
        await _record_failed_login(email)
        raise HTTPException(status_code=401, detail="Invalid email or password")

    await _reset_login_attempts(email)

    if verification_required() and claims.get("email_verified_at") is None:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "EMAIL_NOT_VERIFIED",
                "message": "Please verify your email address before signing in.",
            },
        )

    return claims


@router.post("/token", response_model=TokenResponse)
async def exchange_token(body: TokenRequest, request: Request) -> TokenResponse:
    """Issue a SMART JWT.

    Path 1 — email/password (every environment, password required):
      Looks up user from DB, queries primary position, builds position-aware
      JWT. SA users get hardcoded SA claims (no position required). Unknown
      email and wrong password both return the same generic 401
      INVALID_CREDENTIALS — no account enumeration.

    Path 2 — dev_email (ENVIRONMENT=local only):
      Same lookup/position logic, password optional — local scripts/e2e shortcut.

    Cognito is not used at launch.
    """
    now = datetime.now(timezone.utc)

    if body.email is not None:
        if not body.password:
            raise HTTPException(
                status_code=422,
                detail={"code": "PASSWORD_REQUIRED", "message": "Password is required"},
            )
        # Per-IP login limit — email/password path only, never dev_email.
        await rate_limit_hit("login", client_ip(request))
        try:
            claims = await _password_login(body.email, body.password)
        except HTTPException as exc:
            if exc.status_code == 401:
                raise HTTPException(
                    status_code=401,
                    detail={"code": "INVALID_CREDENTIALS", "message": "Invalid email or password"},
                ) from None
            raise

    elif body.dev_email is not None:
        if ENVIRONMENT != "local":
            raise HTTPException(
                status_code=403,
                detail="dev_email bypass is only available when ENVIRONMENT=local",
            )
        claims = await _password_login(body.dev_email, body.dev_password)

    else:
        raise HTTPException(
            status_code=422,
            detail="Provide email and password",
        )

    tenant_slug          = claims.get("tenant_slug")
    must_reset_password  = bool(claims.get("must_reset_password", False))
    terms_acceptance_required = bool(claims.get("terms_acceptance_required", False))

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

    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return TokenResponse(
        access_token=token,
        expires_in=JWT_EXPIRE * 60,
        tenant_slug=tenant_slug,
        must_reset_password=must_reset_password,
        terms_acceptance_required=terms_acceptance_required,
    )


class ChangePasswordByIdRequest(BaseModel):
    user_id:          str
    current_password: Optional[str] = None   # optional for must_reset users
    new_password:     str


@router.patch("/password/{user_id}", response_model=dict)
async def change_password_by_id(user_id: str, body: ChangePasswordByIdRequest, request: Request) -> dict:
    """Change password for a user identified by user_id.

    Requires a valid SMART Bearer JWT whose sub == user_id — available in
    every environment.

    For users with must_reset_password=true (PENDING_SETUP role — new accounts
    awaiting position assignment), current_password may be omitted because the
    user may have been given a temporary password they cannot verify without
    first logging in.  All other active users must supply current_password.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = auth_header.removeprefix("Bearer ")
    try:
        token_payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if str(token_payload.get("sub", "")) != user_id:
        raise HTTPException(status_code=403, detail="Cannot change another user's password")

    if len(body.new_password) < 8:
        raise HTTPException(status_code=422, detail="New password must be at least 8 characters")

    try:
        from shared.db.session import AsyncSessionLocal
        from sqlalchemy import text as sa_text
        async with AsyncSessionLocal() as db:
            row = (await db.execute(
                sa_text("SELECT * FROM auth_user_by_id(:uid)"),
                {"uid": user_id},
            )).fetchone()
            if row is None or not row.is_active:
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
                sa_text("SELECT auth_update_password(:uid, :ph)"),
                {"ph": new_hash, "uid": user_id},
            )
            await db.commit()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

    await revoke_user_tokens(user_id)

    return {"success": True, "message": "Password updated successfully"}


# ── Email verification (S4) ───────────────────────────────────────────────────

class VerifyEmailRequest(BaseModel):
    token: str


class ResendVerificationRequest(BaseModel):
    email: str


@router.post("/verify-email")
async def verify_email(body: VerifyEmailRequest, request: Request) -> dict:
    """Consume a single-use email-verification token. No SMART JWT exists at
    this point (the user may not even have signed in yet), so this route
    carries no @require_permission — it is allowlisted in ci_drift_check.py.
    """
    await rate_limit_hit("verify", client_ip(request))

    from shared.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        async with db.begin():
            user_id = await consume_verification_token(db, body.token)

    if user_id is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_OR_EXPIRED_TOKEN", "message": "This verification link is invalid or has expired."},
        )
    return {"verified": True}


@router.post("/resend-verification", status_code=202)
async def resend_verification(body: ResendVerificationRequest, request: Request) -> dict:
    """Always answers 202 with the same body, whether or not the email
    belongs to a real, active, unverified account — never reveals account
    existence. No @require_permission — allowlisted in ci_drift_check.py.
    """
    email = body.email.strip().lower()
    await rate_limit_hit("resend", client_ip(request))
    await rate_limit_hit("resend", email)

    from shared.db.session import AsyncSessionLocal
    from sqlalchemy import text as sa_text

    async with AsyncSessionLocal() as db:
        async with db.begin():
            row = (await db.execute(
                sa_text("SELECT auth_active_unverified_user_id(:email) AS id"),
                {"email": email},
            )).fetchone()
            raw_token = (
                await issue_verification_token(db, str(row.id))
                if row and row.id is not None else None
            )

    if raw_token is not None:
        try:
            await asyncio.to_thread(send_verification_email, email, raw_token)
        except Exception as exc:  # noqa: BLE001 — best-effort, response is unconditional
            import logging
            logging.getLogger(__name__).warning("Failed to send verification email: %s", exc)

    return {"sent": True}


# ── Password reset (S4 / B2) ──────────────────────────────────────────────────

class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token:        str
    new_password: str


@router.post("/forgot-password", status_code=202)
async def forgot_password(body: ForgotPasswordRequest, request: Request) -> dict:
    """Always answers 202 with the same body, whether or not the email
    belongs to a real, active account — never reveals account existence.
    Tokens are issued for any is_active user (SA included); suspended/
    deactivated tenants still get a token — login stays blocked by tenant
    status, unchanged. No @require_permission — allowlisted in
    ci_drift_check.py.
    """
    email = body.email.strip().lower()
    await rate_limit_hit("forgot", client_ip(request))
    await rate_limit_hit("forgot", email)

    from shared.db.session import AsyncSessionLocal
    from sqlalchemy import text as sa_text

    async with AsyncSessionLocal() as db:
        async with db.begin():
            row = (await db.execute(
                sa_text("SELECT auth_active_user_id(:email) AS id"),
                {"email": email},
            )).fetchone()
            raw_token = (
                await issue_reset_token(db, str(row.id))
                if row and row.id is not None else None
            )

    if raw_token is not None:
        try:
            await asyncio.to_thread(send_reset_email, email, raw_token)
        except Exception as exc:  # noqa: BLE001 — best-effort, response is unconditional
            import logging
            logging.getLogger(__name__).warning("Failed to send reset email: %s", exc)

    return {"sent": True}


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest, request: Request) -> dict:
    """Consume a single-use password-reset token and set a new password.
    No SMART JWT exists at this point, so this route carries no
    @require_permission — allowlisted in ci_drift_check.py.
    """
    await rate_limit_hit("reset", client_ip(request))

    if len(body.new_password) < 8:
        raise HTTPException(
            status_code=422,
            detail={"code": "PASSWORD_TOO_SHORT", "message": "New password must be at least 8 characters"},
        )

    from shared.db.session import AsyncSessionLocal
    from sqlalchemy import text as sa_text

    email_for_lockout: Optional[str] = None

    async with AsyncSessionLocal() as db:
        async with db.begin():
            user_id = await consume_reset_token(db, body.token)
            if user_id is None:
                raise HTTPException(
                    status_code=400,
                    detail={"code": "INVALID_OR_EXPIRED_TOKEN", "message": "This reset link is invalid or has expired."},
                )

            new_hash = _bcrypt.hashpw(body.new_password.encode(), _bcrypt.gensalt()).decode()
            await db.execute(
                sa_text("SELECT auth_apply_password_reset(:uid, :ph)"),
                {"ph": new_hash, "uid": user_id},
            )
            email_row = (await db.execute(
                sa_text("SELECT auth_user_email_by_id(:uid) AS email"),
                {"uid": user_id},
            )).fetchone()
            email_for_lockout = (
                str(email_row.email) if email_row and email_row.email is not None else None
            )

    await revoke_user_tokens(user_id)

    if email_for_lockout is not None:
        await _reset_login_attempts(email_for_lockout)

    return {"reset": True}
