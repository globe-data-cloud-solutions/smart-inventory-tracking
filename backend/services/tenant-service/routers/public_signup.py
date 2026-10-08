"""Public self sign-up — no authentication, no tenant context yet.

Routes are declared as /public/packages and /public/signup, included under
the same "/api/v1/tenants" prefix as every other tenant-service router (so
the full paths are /api/v1/tenants/public/packages and .../public/signup).
Included in main.py BEFORE tenants.router as a matter of policy, though the
two path segments here never actually collide with tenants.router's single-
segment GET /{tenant_id}.

Every handler here is intentionally public (no @require_permission) and is
allowlisted in scripts/ci_drift_check.py. DB access goes through
shared.db.session.AsyncSessionLocal directly — there is no authenticated user
yet to derive a session from.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

import asyncpg
import bcrypt as _bcrypt
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from routers.tenants import (
    VALID_ORGANISATION_TYPES,
    _duplicate_email_http_exception,
    _is_duplicate_email_violation,
    _log_tenant_activity,
    _slugify,
    _validate_slug,
)
from schemas.tenant import DEFAULT_SYSTEM_PLAN_ID
from services.wizard_service import APPROVAL_DEFAULTS
from shared.auth.email_verification import (
    issue_verification_token,
    send_verification_email,
    verification_required,
)
from shared.billing.subscriptions import get_current_price, start_subscription, vat_breakdown
from shared.cache.rate_limit import client_ip, hit_bucket as rate_limit_hit
from shared.db.rls import set_rls_context
from shared.db.session import AsyncSessionLocal
from shared.plans.catalog import apply_package_to_tenant, get_package, list_packages
from shared.utils.responses import SuccessResponse
from shared.utils.terms import get_terms_version

router = APIRouter()

VALID_BILLING_PERIODS = frozenset({"MONTHLY", "ANNUAL"})


# ── Pydantic models ───────────────────────────────────────────────────────────

class PriceOut(BaseModel):
    subtotal: Decimal
    vat_rate: Decimal
    vat_amount: Decimal
    total: Decimal
    currency: str


class PackageOut(BaseModel):
    tier: str
    display_name: Optional[str]
    max_warehouses: Optional[int]
    max_users: Optional[int]
    sku_cap: Optional[int]          # None = unlimited
    feature_flags: dict
    prices: dict[str, PriceOut]     # key: "MONTHLY" | "ANNUAL" — omitted if no current price


class PackagesListOut(BaseModel):
    packages: list[PackageOut]
    terms_version: str


class SignupRequest(BaseModel):
    company_name: str
    slug: Optional[str] = None
    organisation_type: str
    industry: Optional[str] = None
    default_locale: str = "en"
    tier: str
    billing_period: str
    admin_full_name: str
    admin_email: str
    admin_password: str
    phone: Optional[str] = None
    accept_terms: bool
    terms_version: str

    @field_validator("company_name")
    @classmethod
    def _validate_company_name(cls, v: str) -> str:
        v = v.strip()
        if not (2 <= len(v) <= 255):
            raise ValueError("company_name must be 2-255 characters")
        return v

    @field_validator("admin_email")
    @classmethod
    def _validate_admin_email(cls, v: str) -> str:
        # Basic format check only (not full RFC/DNS validation like EmailStr —
        # that rejects valid-looking internal/test domains such as .local).
        v = str(v).strip().lower()
        local_part, _, domain_part = v.partition("@")
        if not local_part or "@" not in v or "." not in domain_part:
            raise ValueError("admin_email must be a valid email address")
        return v

    @field_validator("admin_password")
    @classmethod
    def _validate_password_length(cls, v: str) -> str:
        # Mirrors personnel_v2.UserCreate / UserUpdateRequest's rule (8 chars) —
        # keep this number in sync with that one, not an independent choice.
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class SignupOut(BaseModel):
    tenant_id: str
    slug: str
    company_name: str
    admin_email: str
    tier: str
    billing_period: str
    subscription_status: str
    contract_start: str
    contract_end: str
    price: PriceOut
    email_verification_required: bool
    next_step: str = "SIGN_IN"


# ── GET /public/packages ──────────────────────────────────────────────────────

@router.get("/public/packages", response_model=SuccessResponse[PackagesListOut])
async def list_public_packages(request: Request) -> SuccessResponse[PackagesListOut]:
    await rate_limit_hit("packages", client_ip(request))

    async with AsyncSessionLocal() as db:
        packages = await list_packages(db, public_only=True)
        out: list[PackageOut] = []
        for pkg in packages:
            prices: dict[str, PriceOut] = {}
            for period in ("MONTHLY", "ANNUAL"):
                price_row = await get_current_price(db, pkg["tier"], period)
                if price_row is None:
                    continue
                prices[period] = PriceOut(currency=price_row.currency, **vat_breakdown(price_row.amount))
            out.append(PackageOut(
                tier=pkg["tier"],
                display_name=pkg["display_name"],
                max_warehouses=pkg["max_warehouses"],
                max_users=pkg["max_users"],
                sku_cap=pkg["sku_cap"],
                feature_flags=pkg["feature_flags"],
                prices=prices,
            ))

    return SuccessResponse(data=PackagesListOut(packages=out, terms_version=get_terms_version()))


# ── POST /public/signup ───────────────────────────────────────────────────────

@router.post("/public/signup", status_code=201, response_model=SuccessResponse[SignupOut])
async def public_signup(body: SignupRequest, request: Request) -> SuccessResponse[SignupOut]:
    ip = client_ip(request)
    # Counted BEFORE validation — an attacker spamming invalid bodies still
    # burns their quota.
    await rate_limit_hit("signup", ip)

    if body.organisation_type not in VALID_ORGANISATION_TYPES:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_ORGANISATION_TYPE",
                "message": f"organisation_type must be one of {sorted(VALID_ORGANISATION_TYPES)}.",
            },
        )
    if body.billing_period not in VALID_BILLING_PERIODS:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_BILLING_PERIOD",
                "message": f"billing_period must be one of {sorted(VALID_BILLING_PERIODS)}.",
            },
        )
    if not body.accept_terms:
        raise HTTPException(
            status_code=422,
            detail={"code": "TERMS_NOT_ACCEPTED", "message": "You must accept the terms to sign up."},
        )
    current_terms_version = get_terms_version()
    if body.terms_version != current_terms_version:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "TERMS_VERSION_MISMATCH",
                "message": f"The current terms version is {current_terms_version}.",
            },
        )

    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()

    async with AsyncSessionLocal() as db:
        async with db.begin():
            await set_rls_context(db, str(tenant_id), str(user_id))

            try:
                package = await get_package(db, body.tier)
            except ValueError:
                raise HTTPException(
                    status_code=422,
                    detail={"code": "INVALID_TIER", "message": f"Unknown tier: {body.tier}"},
                )
            if not package["is_public"]:
                raise HTTPException(
                    status_code=422,
                    detail={"code": "INVALID_TIER", "message": f"Tier {body.tier} is not available for self sign-up."},
                )

            # Slug resolution — same rules as SA create_tenant().
            if body.slug is not None:
                candidate = body.slug.strip().lower()
                if not _validate_slug(candidate):
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "code": "INVALID_SLUG",
                            "message": "Slug must be 3-50 characters, lowercase letters/digits/hyphens, "
                                       "and must start and end with a letter or digit.",
                        },
                    )
                slug = candidate
                dup = await db.execute(text("SELECT id FROM tenants WHERE slug = :s"), {"s": slug})
                if dup.fetchone():
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "code": "SLUG_ALREADY_EXISTS",
                            "message": f"The URL identifier '{slug}' is already taken.",
                        },
                    )
            else:
                base_slug = _slugify(body.company_name) or str(tenant_id)[:8]
                slug = base_slug
                row = await db.execute(text("SELECT id FROM tenants WHERE slug = :s"), {"s": slug})
                if row.fetchone():
                    slug = f"{base_slug}-{str(tenant_id)[:8]}"

            # Email is globally unique — never reveal which tenant owns it.
            existing = (await db.execute(
                text("SELECT id FROM users WHERE lower(email) = :email"),
                {"email": body.admin_email},
            )).fetchone()
            if existing:
                raise _duplicate_email_http_exception()

            approval_thresholds = APPROVAL_DEFAULTS[body.organisation_type]

            # 1. INSERT tenants
            try:
                await db.execute(
                    text(
                        "INSERT INTO tenants (id, name, slug, plan_id, default_locale, organisation_type, "
                        "plan_tier, industry, signup_source, approval_thresholds) "
                        "VALUES (:id, :name, :slug, :plan_id, :locale, :org_type, "
                        "CAST(:plan_tier AS plan_tier), :industry, 'SELF_SIGNUP', CAST(:thresholds AS jsonb))"
                    ),
                    {
                        "id": str(tenant_id),
                        "name": body.company_name,
                        "slug": slug,
                        "plan_id": str(DEFAULT_SYSTEM_PLAN_ID),
                        "locale": body.default_locale,
                        "org_type": body.organisation_type,
                        "plan_tier": body.tier,
                        "industry": body.industry,
                        "thresholds": json.dumps(approval_thresholds),
                    },
                )
            except IntegrityError as exc:
                orig = exc.orig
                if isinstance(orig, asyncpg.NotNullViolationError):
                    message = f"Missing required field: '{orig.column_name}'."
                elif isinstance(orig, asyncpg.ForeignKeyViolationError):
                    message = "Referenced plan_id does not exist."
                else:
                    message = "Could not create tenant: one or more fields were invalid."
                raise HTTPException(
                    status_code=422,
                    detail={"code": "TENANT_CREATE_CONSTRAINT_VIOLATION", "message": message},
                ) from exc

            # 2. Package catalog is the single source of limits/sku_cap/flags.
            await apply_package_to_tenant(db, tenant_id, body.tier)

            # 3. INSERT the TA account-owner user.
            pw_hash = _bcrypt.hashpw(body.admin_password.encode(), _bcrypt.gensalt()).decode()
            try:
                await db.execute(
                    text(
                        "INSERT INTO users "
                        "  (id, tenant_id, email, full_name, password_hash, "
                        "   is_active, must_reset_password, system_role, is_account_owner) "
                        "VALUES (:id, :tid, :email, :name, :hash, true, false, 'TA', true)"
                    ),
                    {
                        "id": str(user_id), "tid": str(tenant_id),
                        "email": body.admin_email, "name": body.admin_full_name,
                        "hash": pw_hash,
                    },
                )
            except IntegrityError as exc:
                if _is_duplicate_email_violation(exc):
                    raise _duplicate_email_http_exception() from exc
                raise

            # 4. INSERT the primary contact.
            await db.execute(
                text(
                    "INSERT INTO tenant_contacts (tenant_id, is_primary, full_name, email, phone) "
                    "VALUES (:tid, true, :name, :email, :phone)"
                ),
                {
                    "tid": str(tenant_id), "name": body.admin_full_name,
                    "email": body.admin_email, "phone": body.phone,
                },
            )

            # 5. Start a PENDING_PAYMENT subscription — the tenant is usable
            # immediately; no payment enforcement until a provider is connected.
            try:
                subscription = await start_subscription(
                    db, tenant_id, body.tier, body.billing_period,
                    status="PENDING_PAYMENT", provider="MANUAL", created_by=user_id,
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=422,
                    detail={"code": "PRICE_NOT_AVAILABLE", "message": str(exc)},
                ) from exc

            # 6. INSERT terms acceptance.
            user_agent = (request.headers.get("User-Agent") or "")[:500]
            await db.execute(
                text(
                    "INSERT INTO terms_acceptances (tenant_id, user_id, terms_version, ip_address, user_agent) "
                    "VALUES (:tid, :uid, :tv, :ip, :ua)"
                ),
                {
                    "tid": str(tenant_id), "uid": str(user_id),
                    "tv": body.terms_version, "ip": ip, "ua": user_agent,
                },
            )

            # 7. Activity log entry.
            await _log_tenant_activity(
                db, tenant_id, str(user_id),
                action="SELF_SIGNUP",
                new_value=f"{body.tier}/{body.billing_period}",
            )

            # 8. Issue the (unsent) verification token — sent only after commit.
            raw_token = await issue_verification_token(db, str(user_id))

    # The transaction above has committed. A send failure here must never
    # roll back or fail the sign-up — just log it.
    try:
        await asyncio.to_thread(send_verification_email, body.admin_email, raw_token)
    except Exception as exc:  # noqa: BLE001 — best-effort, sign-up already succeeded
        logging.getLogger(__name__).warning("Failed to send verification email: %s", exc)

    return SuccessResponse(data=SignupOut(
        tenant_id=str(tenant_id),
        slug=slug,
        company_name=body.company_name,
        admin_email=body.admin_email,
        tier=body.tier,
        billing_period=body.billing_period,
        subscription_status=subscription["status"],
        contract_start=subscription["current_period_start"].isoformat()
            if isinstance(subscription["current_period_start"], date)
            else str(subscription["current_period_start"]),
        contract_end=subscription["current_period_end"].isoformat()
            if isinstance(subscription["current_period_end"], date)
            else str(subscription["current_period_end"]),
        price=PriceOut(
            currency=subscription["currency"],
            subtotal=subscription["subtotal"],
            vat_rate=subscription["vat_rate"],
            vat_amount=subscription["vat_amount"],
            total=subscription["total"],
        ),
        email_verification_required=verification_required(),
        next_step="SIGN_IN",
    ))
