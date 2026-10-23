import json
import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import List, Literal, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_current_user, get_db_session
from services.wizard_service import APPROVAL_DEFAULTS
from shared.cache.rate_limit import client_ip
from shared.cache.token_revocation import revoke_tenant_tokens
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.billing.contract_stage import compute_contract_stage, get_tenant_contract_stage
from shared.billing.subscriptions import (
    get_current_addon_price,
    get_current_price,
    period_end,
    start_subscription,
    vat_breakdown,
)
from shared.billing.proration import preview_addon, preview_upgrade
from shared.billing.plan_change import cancel_scheduled_downgrade, change_plan
from shared.plans.catalog import (
    KNOWN_FEATURE_FLAGS,
    UNSET,
    apply_package_to_tenant,
    get_tenant_entitlements,
)
from shared.plans.usage import get_plan_usage
from shared.utils.responses import SuccessResponse
from shared.utils.terms import get_terms_version
from schemas.tenant import TenantCreateRequest, TenantResponse, VALID_PLAN_TIERS

logger = logging.getLogger(__name__)


# ── Contract renewal requests (P2) ───────────────────────────────────────────


class RenewalRequestIn(BaseModel):
    message: Optional[str] = Field(default=None, max_length=500)
    request_type: Literal["RENEWAL", "UPGRADE"] = "RENEWAL"
    requested_tier: Optional[Literal["STARTER", "GROWTH", "ENTERPRISE"]] = None


class RenewalRequestOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    requested_by: uuid.UUID
    requested_by_email: Optional[str]
    message: Optional[str]
    request_type: str
    requested_tier: Optional[str]
    status: str
    handled_by: Optional[uuid.UUID]
    handled_note: Optional[str]
    handled_at: Optional[str]
    created_at: str


class RenewalRequestHandleIn(BaseModel):
    status: Literal["HANDLED", "CANCELLED"]
    note: Optional[str] = Field(default=None, max_length=500)


class SARenewalRequestRow(RenewalRequestOut):
    tenant_name: str
    tenant_slug: Optional[str]
    plan_tier: Optional[str]
    contract_end: Optional[str]


class ContractStatusOpenRequest(BaseModel):
    id: uuid.UUID
    created_at: str


class ContractStatusOut(BaseModel):
    stage: str
    contract_end: Optional[str]
    days_left: Optional[int]
    grace_ends: Optional[str]
    read_only_since: Optional[str]
    open_request: Optional[ContractStatusOpenRequest]


class ContractsOverviewRow(BaseModel):
    tenant_id: uuid.UUID
    name: str
    slug: Optional[str]
    plan_tier: Optional[str]
    contract_end: Optional[str]
    days_left: Optional[int]
    stage: str
    open_request_id: Optional[uuid.UUID]


class ContractsOverviewOut(BaseModel):
    tenants: List[ContractsOverviewRow]
    counts: dict


def _renewal_row_to_out(row) -> RenewalRequestOut:
    return RenewalRequestOut(
        id=row.id,
        tenant_id=row.tenant_id,
        requested_by=row.requested_by,
        requested_by_email=row.requested_by_email,
        message=row.message,
        request_type=row.request_type,
        requested_tier=row.requested_tier,
        status=row.status,
        handled_by=row.handled_by,
        handled_note=row.handled_note,
        handled_at=row.handled_at.isoformat() if row.handled_at else None,
        created_at=row.created_at.isoformat(),
    )


class TenantStatusResponse(BaseModel):
    id: uuid.UUID
    name: str
    status: str


class RegistryContact(BaseModel):
    id: str
    is_primary: bool
    full_name: str
    position_title: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    mobile: Optional[str]


class TenantRegistryRow(BaseModel):
    id: uuid.UUID
    name: str
    slug: Optional[str]
    organisation_type: Optional[str]
    status: str
    plan_tier: Optional[str]
    default_locale: str = "en"  # persisted user-facing locale preference
    contact_name: Optional[str]  # legacy single-contact field
    contact_email: Optional[str]
    contact_phone: Optional[str]
    contract_start: Optional[str]  # ISO date string "YYYY-MM-DD" or None
    contract_end: Optional[str]
    notes: Optional[str]
    sku_cap: Optional[int]
    address_line1: Optional[str]
    address_line2: Optional[str]
    city: Optional[str]
    state_province: Optional[str]
    postal_code: Optional[str]
    country: Optional[str]
    contacts: List[RegistryContact] = []
    user_count: int
    node_count: int
    created_at: str  # ISO datetime string
    ta_name: Optional[str] = None  # TA admin user name
    ta_email: Optional[str] = None  # TA admin user email
    ta_user_id: Optional[str] = None  # TA admin user UUID (for edit link)
    industry: Optional[str] = None
    feature_flags: dict = {}
    # S6: billing/subscription summary columns
    signup_source: str = "SA"  # 'SA' or 'SELF_SIGNUP'
    subscription_status: Optional[str] = None  # live subscription status, or None
    billing_period: Optional[str] = None  # 'MONTHLY' | 'ANNUAL', or None
    current_period_end: Optional[str] = None  # ISO date string, or None
    last_payment_status: Optional[str] = None  # latest payment's status, or None


class TenantContactIn(BaseModel):
    is_primary: bool = False
    full_name: str
    position_title: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None


class TenantAddressIn(BaseModel):
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state_province: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None


class TenantContactsBulkIn(BaseModel):
    address: Optional[TenantAddressIn] = None
    contacts: List[TenantContactIn] = []


class TenantContactOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    is_primary: bool
    full_name: str
    position_title: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    mobile: Optional[str]
    created_at: str


class TenantActivityRow(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    actor_id: uuid.UUID
    actor_email: Optional[str]
    action: str
    old_value: Optional[str]
    new_value: Optional[str]
    note: Optional[str]
    created_at: str


# Must mirror the "organisation_type" PostgreSQL ENUM values in
# backend/migrations/versions/001_initial_schema.py.
VALID_ORGANISATION_TYPES = frozenset({"PRODUCER", "RETAILER", "HYBRID"})


def _is_duplicate_email_violation(exc: IntegrityError) -> bool:
    """True if this IntegrityError wraps a uq_users_email_lower violation."""
    orig = exc.orig
    return (
        isinstance(orig, asyncpg.UniqueViolationError)
        and orig.constraint_name == "uq_users_email_lower"
    )


def _duplicate_email_http_exception() -> HTTPException:
    # Never reveal which tenant already owns the email.
    return HTTPException(
        status_code=409,
        detail={"code": "DUPLICATE_EMAIL", "message": "This email address is already in use."},
    )


def _slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:80]


def _validate_slug(slug: str) -> bool:
    """Return True if slug matches: 3-50 chars, lowercase alphanumeric + hyphens,
    must start and end with alphanumeric (no leading/trailing hyphens)."""
    import re as _re

    return bool(_re.match(r"^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$", slug))


router = APIRouter()


@router.get("/", response_model=SuccessResponse[List[TenantResponse]])
@require_permission(PERMISSIONS.TENANT_LIST)
async def list_tenants(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[List[TenantResponse]]:
    result = await db.execute(
        text(
            "SELECT id, name, slug, organisation_type, onboarding_complete, default_locale, "
            "is_active, status, plan_tier, max_warehouses, max_users "
            "FROM tenants ORDER BY created_at DESC"
        )
    )
    rows = result.fetchall()
    return SuccessResponse(
        data=[
            TenantResponse(
                id=row.id,
                name=row.name,
                slug=row.slug,
                organisation_type=row.organisation_type,
                onboarding_complete=row.onboarding_complete,
                default_locale=row.default_locale,
                is_active=row.is_active,
                status=row.status,
                plan_tier=getattr(row, "plan_tier", "ENTERPRISE"),
                max_warehouses=getattr(row, "max_warehouses", None),
                max_users=getattr(row, "max_users", None),
            )
            for row in rows
        ]
    )


@router.get("/sa/registry", response_model=SuccessResponse[List[TenantRegistryRow]])
@require_permission(PERMISSIONS.TENANT_REGISTRY_VIEW)
async def sa_tenant_registry(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[List[TenantRegistryRow]]:
    """SA-only: full tenant roster with contact, contract, and usage stats."""
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})

    rows = (
        await db.execute(
            text("""
        SELECT
            t.id, t.name, t.slug, t.organisation_type, t.status, t.plan_tier,
            t.default_locale,
            t.contact_name, t.contact_email, t.contact_phone,
            t.contract_start, t.contract_end, t.notes,
            t.sku_cap, t.address_line1, t.address_line2,
            t.city, t.state_province, t.postal_code, t.country,
            t.industry,
            COALESCE(t.feature_flags, '{}'::jsonb) AS feature_flags,
            t.created_at,
            t.signup_source,
            sub.status AS subscription_status,
            sub.billing_period,
            sub.current_period_end,
            pay.status AS last_payment_status,
            (SELECT COUNT(*) FROM users u
             WHERE u.tenant_id = t.id AND u.is_active = true AND u.system_role != 'TA')  AS user_count,
            (SELECT COUNT(*) FROM organization_node n
             WHERE n.tenant_id = t.id AND n.is_active = true)  AS node_count,
            COALESCE(
                (SELECT json_agg(json_build_object(
                    'id',             c.id::text,
                    'is_primary',     c.is_primary,
                    'full_name',      c.full_name,
                    'position_title', c.position_title,
                    'email',          c.email,
                    'phone',          c.phone,
                    'mobile',         c.mobile
                ) ORDER BY c.is_primary DESC, c.created_at ASC)
                 FROM tenant_contacts c WHERE c.tenant_id = t.id),
                '[]'::json
            ) AS contacts,
            (SELECT u.full_name FROM users u
             WHERE u.tenant_id = t.id AND u.system_role = 'TA' AND u.is_active = true
             ORDER BY u.created_at ASC LIMIT 1) AS ta_name,
            (SELECT u.email FROM users u
             WHERE u.tenant_id = t.id AND u.system_role = 'TA' AND u.is_active = true
             ORDER BY u.created_at ASC LIMIT 1) AS ta_email,
            (SELECT u.id::text FROM users u
             WHERE u.tenant_id = t.id AND u.system_role = 'TA' AND u.is_active = true
             ORDER BY u.created_at ASC LIMIT 1) AS ta_user_id
        FROM tenants t
        LEFT JOIN LATERAL (
            SELECT s.status, s.billing_period, s.current_period_end
            FROM subscriptions s
            WHERE s.tenant_id = t.id AND s.status IN ('ACTIVE', 'PENDING_PAYMENT', 'PAST_DUE')
            ORDER BY s.created_at DESC LIMIT 1
        ) sub ON true
        LEFT JOIN LATERAL (
            SELECT p.status
            FROM payments p
            WHERE p.tenant_id = t.id
            ORDER BY p.created_at DESC LIMIT 1
        ) pay ON true
        ORDER BY t.created_at DESC
    """)
        )
    ).fetchall()

    return SuccessResponse(
        data=[
            TenantRegistryRow(
                id=row.id,
                name=row.name,
                slug=row.slug,
                organisation_type=row.organisation_type,
                status=row.status,
                plan_tier=str(row.plan_tier) if row.plan_tier else None,
                default_locale=row.default_locale or "en",
                contact_name=row.contact_name,
                contact_email=row.contact_email,
                contact_phone=row.contact_phone,
                contract_start=str(row.contract_start) if row.contract_start else None,
                contract_end=str(row.contract_end) if row.contract_end else None,
                notes=row.notes,
                sku_cap=row.sku_cap,
                address_line1=row.address_line1,
                address_line2=row.address_line2,
                city=row.city,
                state_province=row.state_province,
                postal_code=row.postal_code,
                country=row.country,
                contacts=[RegistryContact(**c) for c in (row.contacts or [])],
                user_count=int(row.user_count),
                node_count=int(row.node_count),
                created_at=row.created_at.isoformat(),
                ta_name=row.ta_name,
                ta_email=row.ta_email,
                ta_user_id=row.ta_user_id,
                industry=row.industry,
                feature_flags=dict(row.feature_flags) if row.feature_flags else {},
                signup_source=row.signup_source,
                subscription_status=row.subscription_status,
                billing_period=row.billing_period,
                current_period_end=str(row.current_period_end) if row.current_period_end else None,
                last_payment_status=row.last_payment_status,
            )
            for row in rows
        ]
    )


_SA_MANUAL_PATH = Path(__file__).resolve().parent.parent / "static" / "sa_operations_manual.md"


@router.get("/sa/docs/operations-manual")
@require_permission(PERMISSIONS.SA_DOCS_VIEW)
async def sa_docs_operations_manual(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """SA-only: serves the SA Operations Manual (SA-internal, never frontend/public)."""
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})

    try:
        content = _SA_MANUAL_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.error("SA Operations Manual missing at %s", _SA_MANUAL_PATH)
        raise HTTPException(
            status_code=500,
            detail={"code": "SA_MANUAL_MISSING", "message": "SA Operations Manual file not found"},
        )

    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


class TierConfigEntry(BaseModel):
    tier: str
    max_warehouses: Optional[int] = None  # None = unlimited
    max_users: Optional[int] = None  # None = unlimited
    # Read-only catalog fields (migration 070) — optional so existing clients
    # that only send/expect max_warehouses/max_users keep working.
    display_name: Optional[str] = None
    sku_cap: Optional[int] = None
    feature_flags: Optional[dict] = None
    is_public: Optional[bool] = None
    sort_order: Optional[int] = None


class TierConfigUpdateRequest(BaseModel):
    tiers: List[TierConfigEntry]
    reason: Optional[str] = None


@router.get("/platform/tier-config", response_model=SuccessResponse[List[TierConfigEntry]])
@require_permission(PERMISSIONS.PLATFORM_TIER_CONFIG_VIEW)
async def get_platform_tier_config(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[List[TierConfigEntry]]:
    """SA-only: return the full package catalog (platform_tier_config) for all tiers.

    Reads the table only — no hardcoded fallback. The table is seeded by
    migrations 068/070 and is never expected to be empty.
    """
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})
    rows = (
        await db.execute(
            text(
                "SELECT tier, max_warehouses, max_users, display_name, sku_cap, "
                "       feature_flags, is_public, sort_order "
                "FROM platform_tier_config ORDER BY sort_order"
            ),
        )
    ).fetchall()
    return SuccessResponse(
        data=[
            TierConfigEntry(
                tier=row.tier,
                max_warehouses=row.max_warehouses,
                max_users=row.max_users,
                display_name=row.display_name,
                sku_cap=row.sku_cap,
                feature_flags=dict(row.feature_flags) if row.feature_flags else {},
                is_public=row.is_public,
                sort_order=row.sort_order,
            )
            for row in rows
        ]
    )


_EDITABLE_TIER_FIELDS = (
    "max_warehouses",
    "max_users",
    "display_name",
    "sku_cap",
    "is_public",
    "sort_order",
    "feature_flags",
)


@router.patch("/platform/tier-config", response_model=SuccessResponse[List[TierConfigEntry]])
@require_permission(PERMISSIONS.PLATFORM_TIER_CONFIG_EDIT)
async def update_platform_tier_config(
    body: TierConfigUpdateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[List[TierConfigEntry]]:
    """SA-only: partially update the package catalog (platform_tier_config).

    Each entry updates ONLY the fields explicitly present in its request body —
    an omitted field on an existing tier is left untouched. This keeps the legacy
    dashboard modal body ({tier, max_warehouses, max_users}, no `reason`) working
    unchanged: `reason` defaults to "SA tier-config edit" when not supplied, and
    display_name/sku_cap/feature_flags/is_public/sort_order are simply not touched
    when the caller doesn't send them.

    feature_flags, when sent, fully REPLACES the tier's flag set (not a merge) and
    every key must be one of KNOWN_FEATURE_FLAGS — an unknown key is 422
    UNKNOWN_FEATURE_FLAG. At least one tier must remain is_public=true across the
    whole catalog after this request, or 422 NO_PUBLIC_PACKAGE.

    Changes apply to new tenant creation and future plan changes only — existing
    tenants' effective limits/flags (stored per-tenant) are NOT retroactively
    changed. Every field whose value actually changes is logged to
    platform_config_log.
    """
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})

    valid_tiers = {"STARTER", "GROWTH", "ENTERPRISE"}
    for entry in body.tiers:
        if entry.tier not in valid_tiers:
            raise HTTPException(
                status_code=422,
                detail={"code": "INVALID_TIER", "message": f"Unknown tier: {entry.tier}"},
            )
        fields_set = entry.model_fields_set
        if "display_name" in fields_set:
            name = entry.display_name
            if name is None or not (1 <= len(name) <= 60):
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "INVALID_DISPLAY_NAME",
                        "message": "display_name must be 1-60 characters.",
                    },
                )
        if "sku_cap" in fields_set and entry.sku_cap is not None and entry.sku_cap < 1:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "INVALID_SKU_CAP",
                    "message": "sku_cap must be >= 1, or null for unlimited.",
                },
            )
        if "feature_flags" in fields_set and entry.feature_flags:
            unknown = sorted(set(entry.feature_flags) - KNOWN_FEATURE_FLAGS)
            if unknown:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "UNKNOWN_FEATURE_FLAG",
                        "message": f"Unknown feature flag(s): {', '.join(unknown)}",
                    },
                )

    reason = (body.reason or "").strip() or "SA tier-config edit"

    # At least one tier must remain publicly visible across the WHOLE catalog —
    # checked BEFORE any write, using each tier's current DB value for tiers this
    # request doesn't touch.
    current_rows = (
        await db.execute(
            text("SELECT tier, is_public FROM platform_tier_config"),
        )
    ).fetchall()
    by_tier = {entry.tier: entry for entry in body.tiers}
    still_public = False
    for row in current_rows:
        entry = by_tier.get(row.tier)
        effective_public = (
            entry.is_public
            if entry is not None and "is_public" in entry.model_fields_set
            else row.is_public
        )
        if effective_public:
            still_public = True
            break
    if not still_public:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "NO_PUBLIC_PACKAGE",
                "message": "At least one package must remain publicly visible.",
            },
        )

    actor_email = getattr(user, "email", None)

    for entry in body.tiers:
        editable = [f for f in _EDITABLE_TIER_FIELDS if f in entry.model_fields_set]
        if not editable:
            continue

        old_row = (
            await db.execute(
                text(
                    "SELECT max_warehouses, max_users, display_name, sku_cap, "
                    "       feature_flags, is_public, sort_order "
                    "FROM platform_tier_config WHERE tier = :tier"
                ),
                {"tier": entry.tier},
            )
        ).fetchone()

        set_parts = ["updated_at = now()", "updated_by_id = :uid"]
        params: dict = {"tier": entry.tier, "uid": str(user.user_id)}
        for field in editable:
            value = getattr(entry, field)
            if field == "feature_flags":
                set_parts.append("feature_flags = CAST(:feature_flags AS jsonb)")
                params["feature_flags"] = json.dumps(value or {})
            else:
                set_parts.append(f"{field} = :{field}")
                params[field] = value

        await db.execute(
            text(f"UPDATE platform_tier_config SET {', '.join(set_parts)} WHERE tier = :tier"),
            params,
        )

        for field in editable:
            new_val = getattr(entry, field)
            old_val = getattr(old_row, field) if old_row else None
            if field == "feature_flags":
                old_cmp = dict(old_val) if old_val else {}
                new_cmp = new_val or {}
                if old_cmp == new_cmp:
                    continue
                old_str, new_str = json.dumps(old_cmp), json.dumps(new_cmp)
            elif old_val != new_val:
                old_str = str(old_val) if old_val is not None else None
                new_str = str(new_val) if new_val is not None else None
            else:
                continue

            await db.execute(
                text(
                    "INSERT INTO platform_config_log "
                    "  (entity_type, entity_key, field, old_value, new_value, "
                    "   reason, actor_id, actor_email) "
                    "VALUES ('PACKAGE', :tier, :field, :old, :new, :reason, :actor_id, :actor_email)"
                ),
                {
                    "tier": entry.tier,
                    "field": field,
                    "old": old_str,
                    "new": new_str,
                    "reason": reason,
                    "actor_id": str(user.user_id),
                    "actor_email": actor_email,
                },
            )

    rows = (
        await db.execute(
            text(
                "SELECT tier, max_warehouses, max_users, display_name, sku_cap, "
                "       feature_flags, is_public, sort_order "
                "FROM platform_tier_config ORDER BY sort_order"
            ),
        )
    ).fetchall()
    return SuccessResponse(
        data=[
            TierConfigEntry(
                tier=row.tier,
                max_warehouses=row.max_warehouses,
                max_users=row.max_users,
                display_name=row.display_name,
                sku_cap=row.sku_cap,
                feature_flags=dict(row.feature_flags) if row.feature_flags else {},
                is_public=row.is_public,
                sort_order=row.sort_order,
            )
            for row in rows
        ]
    )


class PriceHistoryEntry(BaseModel):
    id: str
    amount: Decimal
    currency: str
    effective_from: str
    reason: str
    created_by: Optional[str] = None
    created_by_email: Optional[str] = None
    created_at: str


class PriceSnapshot(BaseModel):
    id: str
    amount: Decimal
    currency: str
    effective_from: str
    subtotal: Decimal
    vat_rate: Decimal
    vat_amount: Decimal
    total: Decimal


class TierPricing(BaseModel):
    tier: str
    billing_period: str
    current: Optional[PriceSnapshot] = None
    scheduled: List[PriceHistoryEntry] = []
    history: List[PriceHistoryEntry] = []


_VALID_TIERS = ("STARTER", "GROWTH", "ENTERPRISE")
_VALID_BILLING_PERIODS = ("MONTHLY", "ANNUAL")


@router.get("/platform/packages/prices", response_model=SuccessResponse[List[TierPricing]])
@require_permission(PERMISSIONS.PLATFORM_TIER_CONFIG_VIEW)
async def get_platform_package_prices(
    tier: Optional[str] = None,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[List[TierPricing]]:
    """SA-only: price history per tier + billing_period.

    package_prices is append-only. For each (tier, billing_period): "current" is the
    latest row with effective_from <= now() (the same row get_current_price() would
    pick), "scheduled" are rows with effective_from in the future, and "history" is
    every row for that tier/period, newest first.
    """
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})

    if tier is not None and tier not in _VALID_TIERS:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_TIER", "message": f"Unknown tier: {tier}"},
        )
    tiers = [tier] if tier else list(_VALID_TIERS)

    now = datetime.now(timezone.utc)
    result: List[TierPricing] = []
    for t in tiers:
        for period in _VALID_BILLING_PERIODS:
            rows = (
                await db.execute(
                    text(
                        "SELECT pp.id, pp.amount, pp.currency, pp.effective_from, pp.reason, "
                        "       pp.created_by, pp.created_at, u.email AS created_by_email "
                        "FROM package_prices pp "
                        "LEFT JOIN users u ON u.id = pp.created_by "
                        "WHERE pp.tier = :tier AND pp.billing_period = :period "
                        "ORDER BY pp.effective_from DESC, pp.created_at DESC"
                    ),
                    {"tier": t, "period": period},
                )
            ).fetchall()

            history = [
                PriceHistoryEntry(
                    id=str(r.id),
                    amount=r.amount,
                    currency=r.currency,
                    effective_from=r.effective_from.isoformat(),
                    reason=r.reason,
                    created_by=str(r.created_by) if r.created_by else None,
                    created_by_email=r.created_by_email,
                    created_at=r.created_at.isoformat(),
                )
                for r in rows
            ]
            scheduled = [h for h, r in zip(history, rows) if r.effective_from > now]
            current_row = next((r for r in rows if r.effective_from <= now), None)
            current = None
            if current_row is not None:
                breakdown = vat_breakdown(Decimal(current_row.amount))
                current = PriceSnapshot(
                    id=str(current_row.id),
                    amount=current_row.amount,
                    currency=current_row.currency,
                    effective_from=current_row.effective_from.isoformat(),
                    subtotal=breakdown["subtotal"],
                    vat_rate=breakdown["vat_rate"],
                    vat_amount=breakdown["vat_amount"],
                    total=breakdown["total"],
                )

            result.append(
                TierPricing(
                    tier=t,
                    billing_period=period,
                    current=current,
                    scheduled=scheduled,
                    history=history,
                )
            )

    return SuccessResponse(data=result)


class PriceCreateRequest(BaseModel):
    billing_period: str
    amount: Decimal
    effective_from: Optional[datetime] = None
    reason: str


@router.post(
    "/platform/packages/{tier}/prices", response_model=SuccessResponse[dict], status_code=201
)
@require_permission(PERMISSIONS.PLATFORM_TIER_CONFIG_EDIT)
async def create_platform_package_price(
    tier: str,
    body: PriceCreateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[dict]:
    """SA-only: post a new (append-only) price for tier + billing_period.

    Existing subscriptions are untouched — a price change applies only at each
    subscription's next renewal (shared.billing.payments.next_invoice_period), never
    retroactively to the currently-invoiced period.

    effective_from defaults to now() and must not be more than 5 minutes in the past.
    Posting a correcting price with the SAME effective_from as a wrong one is
    supported: get_current_price()'s tie-break on created_at DESC means the newer
    (correcting) row becomes current.
    """
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})

    if tier not in _VALID_TIERS:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_TIER", "message": f"Unknown tier: {tier}"},
        )
    if body.billing_period not in _VALID_BILLING_PERIODS:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_BILLING_PERIOD",
                "message": f"billing_period must be one of {list(_VALID_BILLING_PERIODS)}",
            },
        )
    if body.amount < 0 or -body.amount.as_tuple().exponent > 2:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_AMOUNT",
                "message": "amount must be >= 0 with at most 2 decimal places.",
            },
        )

    reason = body.reason.strip() if body.reason else ""
    if not reason:
        raise HTTPException(
            status_code=422, detail={"code": "REASON_REQUIRED", "message": "reason is required."}
        )

    now = datetime.now(timezone.utc)
    effective_from = body.effective_from or now
    if effective_from.tzinfo is None:
        effective_from = effective_from.replace(tzinfo=timezone.utc)
    if effective_from < now - timedelta(minutes=5):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "EFFECTIVE_FROM_IN_PAST",
                "message": "effective_from must not be more than 5 minutes in the past.",
            },
        )

    old_price = await get_current_price(db, tier, body.billing_period)

    new_id = (
        await db.execute(
            text(
                "INSERT INTO package_prices (tier, billing_period, amount, effective_from, reason, created_by) "
                "VALUES (:tier, :period, :amount, :eff, :reason, :uid) RETURNING id"
            ),
            {
                "tier": tier,
                "period": body.billing_period,
                "amount": body.amount,
                "eff": effective_from,
                "reason": reason,
                "uid": str(user.user_id),
            },
        )
    ).scalar_one()

    await db.execute(
        text(
            "INSERT INTO platform_config_log "
            "  (entity_type, entity_key, field, old_value, new_value, reason, actor_id, actor_email) "
            "VALUES ('PRICE', :key, 'amount', :old, :new, :reason, :actor_id, :actor_email)"
        ),
        {
            "key": f"{tier}/{body.billing_period}",
            "old": str(old_price.amount) if old_price else None,
            "new": f"{body.amount} from {effective_from.isoformat()}",
            "reason": reason,
            "actor_id": str(user.user_id),
            "actor_email": getattr(user, "email", None),
        },
    )

    return SuccessResponse(
        data={
            "id": str(new_id),
            "tier": tier,
            "billing_period": body.billing_period,
            "amount": body.amount,
            "effective_from": effective_from.isoformat(),
            "message": "Existing subscriptions pay this price starting from their next renewal.",
        }
    )


class ConfigLogEntry(BaseModel):
    id: str
    entity_type: str
    entity_key: str
    field: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    reason: Optional[str] = None
    actor_email: Optional[str] = None
    created_at: str


@router.get("/platform/config-log", response_model=SuccessResponse[List[ConfigLogEntry]])
@require_permission(PERMISSIONS.PLATFORM_TIER_CONFIG_VIEW)
async def get_platform_config_log(
    entity_type: Optional[str] = None,
    entity_key: Optional[str] = None,
    limit: int = 100,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[List[ConfigLogEntry]]:
    """SA-only: platform_config_log listing, newest first, optionally filtered."""
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})

    limit = min(max(limit, 1), 500)
    conditions = []
    params: dict = {"limit": limit}
    if entity_type:
        conditions.append("entity_type = :entity_type")
        params["entity_type"] = entity_type
    if entity_key:
        conditions.append("entity_key = :entity_key")
        params["entity_key"] = entity_key
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    rows = (
        await db.execute(
            text(
                f"SELECT id, entity_type, entity_key, field, old_value, new_value, "
                f"       reason, actor_email, created_at "
                f"FROM platform_config_log {where_clause} "
                f"ORDER BY created_at DESC LIMIT :limit"
            ),
            params,
        )
    ).fetchall()

    return SuccessResponse(
        data=[
            ConfigLogEntry(
                id=str(row.id),
                entity_type=row.entity_type,
                entity_key=row.entity_key,
                field=row.field,
                old_value=row.old_value,
                new_value=row.new_value,
                reason=row.reason,
                actor_email=row.actor_email,
                created_at=row.created_at.isoformat(),
            )
            for row in rows
        ]
    )


# ── Add-on catalog (S10) — mirrors the package tier-config/prices routes ────


class AddonPricing(BaseModel):
    billing_period: str
    current: Optional[PriceSnapshot] = None
    scheduled: List[PriceHistoryEntry] = []
    history: List[PriceHistoryEntry] = []


class AddonCatalogEntry(BaseModel):
    code: str
    display_name: str
    description: Optional[str] = None
    is_active: bool
    is_public: bool
    sort_order: int
    prices: List[AddonPricing]


async def _addon_pricing(db: AsyncSession, addon_code: str) -> List[AddonPricing]:
    now = datetime.now(timezone.utc)
    result: List[AddonPricing] = []
    for period in _VALID_BILLING_PERIODS:
        rows = (
            await db.execute(
                text(
                    "SELECT ap.id, ap.amount, ap.currency, ap.effective_from, ap.reason, "
                    "       ap.created_by, ap.created_at, u.email AS created_by_email "
                    "FROM addon_prices ap "
                    "LEFT JOIN users u ON u.id = ap.created_by "
                    "WHERE ap.addon_code = :code AND ap.billing_period = :period "
                    "ORDER BY ap.effective_from DESC, ap.created_at DESC"
                ),
                {"code": addon_code, "period": period},
            )
        ).fetchall()

        history = [
            PriceHistoryEntry(
                id=str(r.id),
                amount=r.amount,
                currency=r.currency,
                effective_from=r.effective_from.isoformat(),
                reason=r.reason,
                created_by=str(r.created_by) if r.created_by else None,
                created_by_email=r.created_by_email,
                created_at=r.created_at.isoformat(),
            )
            for r in rows
        ]
        scheduled = [h for h, r in zip(history, rows) if r.effective_from > now]
        current_row = next((r for r in rows if r.effective_from <= now), None)
        current = None
        if current_row is not None:
            breakdown = vat_breakdown(Decimal(current_row.amount))
            current = PriceSnapshot(
                id=str(current_row.id),
                amount=current_row.amount,
                currency=current_row.currency,
                effective_from=current_row.effective_from.isoformat(),
                subtotal=breakdown["subtotal"],
                vat_rate=breakdown["vat_rate"],
                vat_amount=breakdown["vat_amount"],
                total=breakdown["total"],
            )
        result.append(
            AddonPricing(
                billing_period=period, current=current, scheduled=scheduled, history=history
            )
        )
    return result


@router.get("/platform/addons", response_model=SuccessResponse[List[AddonCatalogEntry]])
@require_permission(PERMISSIONS.PLATFORM_TIER_CONFIG_VIEW)
async def get_platform_addons(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[List[AddonCatalogEntry]]:
    """SA-only: the add-on catalog with current/scheduled/history prices per
    billing_period, same shape as GET /platform/packages/prices."""
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})

    rows = (
        await db.execute(
            text(
                "SELECT code, display_name, description, is_active, is_public, sort_order "
                "FROM platform_addons ORDER BY sort_order"
            ),
        )
    ).fetchall()
    return SuccessResponse(
        data=[
            AddonCatalogEntry(
                code=row.code,
                display_name=row.display_name,
                description=row.description,
                is_active=row.is_active,
                is_public=row.is_public,
                sort_order=row.sort_order,
                prices=await _addon_pricing(db, row.code),
            )
            for row in rows
        ]
    )


class AddonUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    is_public: Optional[bool] = None
    sort_order: Optional[int] = None
    reason: str


_EDITABLE_ADDON_FIELDS = ("display_name", "description", "is_active", "is_public", "sort_order")


@router.patch("/platform/addons/{code}", response_model=SuccessResponse[AddonCatalogEntry])
@require_permission(PERMISSIONS.PLATFORM_TIER_CONFIG_EDIT)
async def update_platform_addon(
    code: str,
    body: AddonUpdateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[AddonCatalogEntry]:
    """SA-only: partial update of one add-on's catalog entry. `reason` is
    required; every field that actually changes is logged to
    platform_config_log (entity_type='ADDON')."""
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})

    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(
            status_code=422, detail={"code": "REASON_REQUIRED", "message": "reason is required."}
        )

    old_row = (
        await db.execute(
            text(
                "SELECT display_name, description, is_active, is_public, sort_order "
                "FROM platform_addons WHERE code = :code"
            ),
            {"code": code},
        )
    ).fetchone()
    if old_row is None:
        raise HTTPException(
            status_code=404, detail={"code": "ADDON_NOT_FOUND", "message": "Unknown add-on."}
        )

    if "display_name" in body.model_fields_set:
        name = body.display_name
        if name is None or not (1 <= len(name) <= 60):
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "INVALID_DISPLAY_NAME",
                    "message": "display_name must be 1-60 characters.",
                },
            )

    editable = [f for f in _EDITABLE_ADDON_FIELDS if f in body.model_fields_set]
    if editable:
        set_parts = ["updated_at = now()", "updated_by_id = :uid"]
        params: dict = {"code": code, "uid": str(user.user_id)}
        for field in editable:
            set_parts.append(f"{field} = :{field}")
            params[field] = getattr(body, field)
        await db.execute(
            text(f"UPDATE platform_addons SET {', '.join(set_parts)} WHERE code = :code"),
            params,
        )

        for field in editable:
            new_val = getattr(body, field)
            old_val = getattr(old_row, field)
            if old_val == new_val:
                continue
            await db.execute(
                text(
                    "INSERT INTO platform_config_log "
                    "  (entity_type, entity_key, field, old_value, new_value, "
                    "   reason, actor_id, actor_email) "
                    "VALUES ('ADDON', :code, :field, :old, :new, :reason, :actor_id, :actor_email)"
                ),
                {
                    "code": code,
                    "field": field,
                    "old": str(old_val) if old_val is not None else None,
                    "new": str(new_val) if new_val is not None else None,
                    "reason": reason,
                    "actor_id": str(user.user_id),
                    "actor_email": getattr(user, "email", None),
                },
            )

    row = (
        await db.execute(
            text(
                "SELECT code, display_name, description, is_active, is_public, sort_order "
                "FROM platform_addons WHERE code = :code"
            ),
            {"code": code},
        )
    ).fetchone()
    return SuccessResponse(
        data=AddonCatalogEntry(
            code=row.code,
            display_name=row.display_name,
            description=row.description,
            is_active=row.is_active,
            is_public=row.is_public,
            sort_order=row.sort_order,
            prices=await _addon_pricing(db, row.code),
        )
    )


@router.post(
    "/platform/addons/{code}/prices", response_model=SuccessResponse[dict], status_code=201
)
@require_permission(PERMISSIONS.PLATFORM_TIER_CONFIG_EDIT)
async def create_platform_addon_price(
    code: str,
    body: PriceCreateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[dict]:
    """SA-only: post a new (append-only) price for an add-on + billing_period.
    Same rules as POST /platform/packages/{tier}/prices: reason required,
    effective_from not more than 5 minutes in the past, append-only so a
    correction posts a new row with the same effective_from."""
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})

    addon_row = (
        await db.execute(
            text("SELECT code FROM platform_addons WHERE code = :code"),
            {"code": code},
        )
    ).fetchone()
    if addon_row is None:
        raise HTTPException(
            status_code=404, detail={"code": "ADDON_NOT_FOUND", "message": "Unknown add-on."}
        )

    if body.billing_period not in _VALID_BILLING_PERIODS:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_BILLING_PERIOD",
                "message": f"billing_period must be one of {list(_VALID_BILLING_PERIODS)}",
            },
        )
    if body.amount < 0 or -body.amount.as_tuple().exponent > 2:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_AMOUNT",
                "message": "amount must be >= 0 with at most 2 decimal places.",
            },
        )

    reason = body.reason.strip() if body.reason else ""
    if not reason:
        raise HTTPException(
            status_code=422, detail={"code": "REASON_REQUIRED", "message": "reason is required."}
        )

    now = datetime.now(timezone.utc)
    effective_from = body.effective_from or now
    if effective_from.tzinfo is None:
        effective_from = effective_from.replace(tzinfo=timezone.utc)
    if effective_from < now - timedelta(minutes=5):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "EFFECTIVE_FROM_IN_PAST",
                "message": "effective_from must not be more than 5 minutes in the past.",
            },
        )

    old_price = await get_current_addon_price(db, code, body.billing_period)

    new_id = (
        await db.execute(
            text(
                "INSERT INTO addon_prices (addon_code, billing_period, amount, effective_from, reason, created_by) "
                "VALUES (:code, :period, :amount, :eff, :reason, :uid) RETURNING id"
            ),
            {
                "code": code,
                "period": body.billing_period,
                "amount": body.amount,
                "eff": effective_from,
                "reason": reason,
                "uid": str(user.user_id),
            },
        )
    ).scalar_one()

    await db.execute(
        text(
            "INSERT INTO platform_config_log "
            "  (entity_type, entity_key, field, old_value, new_value, reason, actor_id, actor_email) "
            "VALUES ('ADDON_PRICE', :key, 'amount', :old, :new, :reason, :actor_id, :actor_email)"
        ),
        {
            "key": f"{code}/{body.billing_period}",
            "old": str(old_price.amount) if old_price else None,
            "new": f"{body.amount} from {effective_from.isoformat()}",
            "reason": reason,
            "actor_id": str(user.user_id),
            "actor_email": getattr(user, "email", None),
        },
    )

    return SuccessResponse(
        data={
            "id": str(new_id),
            "addon_code": code,
            "billing_period": body.billing_period,
            "amount": body.amount,
            "effective_from": effective_from.isoformat(),
            "message": "Existing purchased add-ons pay this price starting from their next renewal invoice.",
        }
    )


@router.get("/sa/{tenant_id}/activity", response_model=SuccessResponse[List[TenantActivityRow]])
@require_permission(PERMISSIONS.TENANT_ACTIVITY_VIEW)
async def sa_tenant_activity(
    tenant_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[List[TenantActivityRow]]:
    """SA-only: paginated activity log for a single tenant."""
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})

    exists = (
        await db.execute(
            text("SELECT id FROM tenants WHERE id = :tid"),
            {"tid": str(tenant_id)},
        )
    ).fetchone()
    if not exists:
        raise HTTPException(status_code=404, detail="Tenant not found")

    rows = (
        await db.execute(
            text("""
            SELECT id, tenant_id, actor_id, actor_email,
                   action, old_value, new_value, note, created_at
            FROM tenant_activity_log
            WHERE tenant_id = :tid
            ORDER BY created_at DESC
            LIMIT :lim OFFSET :off
        """),
            {"tid": str(tenant_id), "lim": limit, "off": offset},
        )
    ).fetchall()

    return SuccessResponse(
        data=[
            TenantActivityRow(
                id=row.id,
                tenant_id=row.tenant_id,
                actor_id=row.actor_id,
                actor_email=row.actor_email,
                action=row.action,
                old_value=row.old_value,
                new_value=row.new_value,
                note=row.note,
                created_at=row.created_at.isoformat(),
            )
            for row in rows
        ]
    )


@router.get("/sa/renewal-requests", response_model=SuccessResponse[List[SARenewalRequestRow]])
@require_permission(PERMISSIONS.TENANT_RENEWAL_MANAGE)
async def sa_list_renewal_requests(
    status: str = Query("OPEN", pattern="^(OPEN|HANDLED|ALL)$"),
    type: str = Query("ALL", pattern="^(RENEWAL|UPGRADE|ALL)$"),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[List[SARenewalRequestRow]]:
    """SA-only: renewal/upgrade request queue, newest first. Same cross-tenant
    read pattern as sa_tenant_registry() above — the app's DB role owns these
    RLS-enabled tables and isn't FORCE-restricted, so a plain cross-tenant
    JOIN works without any special RLS bypass."""
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})

    conditions = []
    if status == "OPEN":
        conditions.append("r.status = 'OPEN'")
    elif status == "HANDLED":
        conditions.append("r.status IN ('HANDLED', 'CANCELLED')")
    # status == "ALL" -> no filter
    if type != "ALL":
        conditions.append("r.request_type = :rtype")
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    rows = (
        await db.execute(
            text(f"""
            SELECT r.id, r.tenant_id, t.name AS tenant_name, t.slug AS tenant_slug,
                   t.plan_tier, t.contract_end,
                   r.requested_by, r.requested_by_email, r.message,
                   r.request_type, r.requested_tier, r.status,
                   r.handled_by, r.handled_note, r.handled_at, r.created_at
            FROM tenant_renewal_requests r
            JOIN tenants t ON t.id = r.tenant_id
            {where}
            ORDER BY r.created_at DESC
        """),
            {"rtype": type} if type != "ALL" else {},
        )
    ).fetchall()

    return SuccessResponse(
        data=[
            SARenewalRequestRow(
                id=row.id,
                tenant_id=row.tenant_id,
                tenant_name=row.tenant_name,
                tenant_slug=row.tenant_slug,
                plan_tier=row.plan_tier,
                contract_end=str(row.contract_end) if row.contract_end else None,
                requested_by=row.requested_by,
                requested_by_email=row.requested_by_email,
                message=row.message,
                request_type=row.request_type,
                requested_tier=row.requested_tier,
                status=row.status,
                handled_by=row.handled_by,
                handled_note=row.handled_note,
                handled_at=row.handled_at.isoformat() if row.handled_at else None,
                created_at=row.created_at.isoformat(),
            )
            for row in rows
        ]
    )


@router.patch(
    "/sa/renewal-requests/{request_id}", response_model=SuccessResponse[RenewalRequestOut]
)
@require_permission(PERMISSIONS.TENANT_RENEWAL_MANAGE)
async def sa_handle_renewal_request(
    request_id: uuid.UUID,
    body: RenewalRequestHandleIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[RenewalRequestOut]:
    """SA-only: mark a renewal or upgrade request HANDLED or CANCELLED. Only
    an OPEN request can be transitioned — any other current status is a 409.
    This never changes the tenant's plan; the plan change itself goes through
    the existing tier-change endpoint (S13)."""
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})

    existing = (
        await db.execute(
            text(
                "SELECT id, tenant_id, status, request_type FROM tenant_renewal_requests WHERE id = :id"
            ),
            {"id": str(request_id)},
        )
    ).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Renewal request not found")
    if existing.status != "OPEN":
        raise HTTPException(
            status_code=409,
            detail={"code": "RENEWAL_REQUEST_NOT_OPEN", "status": existing.status},
        )

    updated = (
        await db.execute(
            text(
                "UPDATE tenant_renewal_requests "
                "SET status = :status, handled_by = :hb, handled_note = :note, handled_at = now() "
                "WHERE id = :id "
                "RETURNING id, tenant_id, requested_by, requested_by_email, message, "
                "request_type, requested_tier, status, handled_by, handled_note, handled_at, created_at"
            ),
            {
                "status": body.status,
                "hb": str(user.user_id),
                "note": body.note,
                "id": str(request_id),
            },
        )
    ).fetchone()

    if existing.request_type == "UPGRADE":
        action = "UPGRADE_HANDLED" if body.status == "HANDLED" else "UPGRADE_CANCELLED"
    else:
        action = "RENEWAL_HANDLED" if body.status == "HANDLED" else "RENEWAL_CANCELLED"
    await _log_tenant_activity(
        db,
        existing.tenant_id,
        str(user.user_id),
        action=action,
        old_value="OPEN",
        new_value=body.status,
        note=body.note,
    )

    return SuccessResponse(data=_renewal_row_to_out(updated))


@router.get("/sa/contracts/overview", response_model=SuccessResponse[ContractsOverviewOut])
@require_permission(PERMISSIONS.TENANT_RENEWAL_MANAGE)
async def sa_contracts_overview(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[ContractsOverviewOut]:
    """SA-only: every non-DEACTIVATED tenant whose contract stage is
    EXPIRING, GRACE, or READ_ONLY, soonest-expiring first, plus per-stage
    counts. Same cross-tenant read pattern as sa_tenant_registry() above."""
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})

    rows = (
        await db.execute(
            text("""
        SELECT t.id, t.name, t.slug, t.plan_tier, t.contract_end,
               (SELECT r.id FROM tenant_renewal_requests r
                WHERE r.tenant_id = t.id AND r.status = 'OPEN' AND r.request_type = 'RENEWAL'
                ORDER BY r.created_at DESC LIMIT 1) AS open_request_id
        FROM tenants t
        WHERE t.status != 'DEACTIVATED'
    """)
        )
    ).fetchall()

    today = datetime.utcnow().date()
    counts = {"EXPIRING": 0, "GRACE": 0, "READ_ONLY": 0}
    overview_rows: List[ContractsOverviewRow] = []

    for row in rows:
        stage = compute_contract_stage(row.contract_end, today)
        if stage not in counts:
            continue
        days_left = (row.contract_end - today).days if row.contract_end else None
        counts[stage] += 1
        overview_rows.append(
            ContractsOverviewRow(
                tenant_id=row.id,
                name=row.name,
                slug=row.slug,
                plan_tier=row.plan_tier,
                contract_end=str(row.contract_end) if row.contract_end else None,
                days_left=days_left,
                stage=stage,
                open_request_id=row.open_request_id,
            )
        )

    overview_rows.sort(key=lambda r: r.days_left if r.days_left is not None else 10**9)

    return SuccessResponse(data=ContractsOverviewOut(tenants=overview_rows, counts=counts))


@router.post("/", status_code=201, response_model=SuccessResponse[TenantResponse])
@require_permission(PERMISSIONS.TENANT_CREATE)
async def create_tenant(
    body: TenantCreateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TenantResponse]:
    from sqlalchemy import text

    tenant_id = uuid.uuid4()

    if body.organisation_type not in VALID_ORGANISATION_TYPES:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_ORGANISATION_TYPE",
                "message": f"organisation_type must be one of {sorted(VALID_ORGANISATION_TYPES)}, "
                f"got '{body.organisation_type}'.",
            },
        )

    if body.plan_tier not in VALID_PLAN_TIERS:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_TIER",
                "message": f"plan_tier must be one of {sorted(VALID_PLAN_TIERS)}, "
                f"got '{body.plan_tier}'.",
            },
        )

    if body.billing_period not in _VALID_BILLING_PERIODS:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_BILLING_PERIOD",
                "message": f"billing_period must be one of {list(_VALID_BILLING_PERIODS)}, "
                f"got '{body.billing_period}'.",
            },
        )

    def _parse_contract_date(s: Optional[str], field: str) -> Optional[date]:
        if s is None:
            return None
        try:
            return date.fromisoformat(s)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "INVALID_CONTRACT_DATES",
                    "field": field,
                    "message": f"'{field}' must be a valid ISO date (YYYY-MM-DD).",
                },
            )

    contract_start_parsed = _parse_contract_date(body.contract_start, "contract_start")
    contract_end_parsed = _parse_contract_date(body.contract_end, "contract_end")
    if (
        contract_start_parsed
        and contract_end_parsed
        and contract_end_parsed <= contract_start_parsed
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_CONTRACT_DATES",
                "field": "contract_end",
                "message": "contract_end must be after contract_start.",
            },
        )
    # contract_end given WITHOUT contract_start implicitly starts the contract
    # today (see effective_start below) — it must still land in the future,
    # or the contract would already be expired at creation.
    if (
        contract_start_parsed is None
        and contract_end_parsed is not None
        and contract_end_parsed <= date.today()
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_CONTRACT_DATES",
                "field": "contract_end",
                "message": "contract_end must be after today when contract_start is not given.",
            },
        )

    # Slug resolution: use caller-provided slug (validated) or auto-generate from name.
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
        # Check uniqueness of the caller-provided slug — never auto-resolve.
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
        # Auto-generate from name; append short UUID suffix on collision.
        base_slug = _slugify(body.name) or str(tenant_id)[:8]
        slug = base_slug
        row = await db.execute(text("SELECT id FROM tenants WHERE slug = :s"), {"s": slug})
        if row.fetchone():
            slug = f"{base_slug}-{str(tenant_id)[:8]}"
    try:
        await db.execute(
            text(
                "INSERT INTO tenants (id, name, slug, plan_id, default_locale, organisation_type, "
                "plan_tier, industry) "
                "VALUES (:id, :name, :slug, :plan_id, :locale, :org_type, "
                "CAST(:plan_tier AS plan_tier), :industry)"
            ),
            {
                "id": str(tenant_id),
                "name": body.name,
                "slug": slug,
                "plan_id": str(body.plan_id),
                "locale": body.default_locale,
                "org_type": body.organisation_type,
                "plan_tier": body.plan_tier,
                "industry": body.industry,
            },
        )
    except IntegrityError as exc:
        # Defense-in-depth: organisation_type is validated above, but this also
        # covers any other NOT NULL / FK / enum mismatch on this INSERT (e.g. an
        # unrecognized plan_id) without leaking a raw 500 + SQL detail to the client.
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

    # Package catalog is the single source of limits/sku_cap/flags (CLAUDE.md §15).
    # sku_cap applies to every organisation type — only overridden when the
    # caller explicitly sent it.
    try:
        await apply_package_to_tenant(
            db,
            tenant_id,
            body.plan_tier,
            sku_cap=body.sku_cap if "sku_cap" in body.model_fields_set else UNSET,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_TIER", "message": str(exc)},
        ) from exc

    # Package catalog set the entitlements above; this snapshots the current
    # price and starts the subscription's first billing period (CLAUDE.md §15
    # decision B). signup_source stays the column default 'SA'. The subscription's
    # first period starts on the contract start (or today if none given);
    # start_subscription() only fills tenants.contract_start/end when both are
    # still NULL, so an explicit contract below always wins.
    try:
        subscription_result = await start_subscription(
            db,
            tenant_id,
            body.plan_tier,
            body.billing_period,
            status="ACTIVE",
            provider="MANUAL",
            created_by=user.user_id,
            start=contract_start_parsed,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "PRICE_NOT_AVAILABLE", "message": str(exc)},
        ) from exc

    # Contract (the commercial agreement) is independent of the billing period
    # (CLAUDE.md §15 decision B) — when the caller sent contract dates, they win
    # outright over whatever start_subscription() derived. contract_end defaults
    # to the subscription's own period end when only contract_start was sent.
    if contract_start_parsed is not None or contract_end_parsed is not None:
        effective_start = contract_start_parsed or date.today()
        effective_end = contract_end_parsed or period_end(effective_start, body.billing_period)
        await db.execute(
            text("UPDATE tenants SET contract_start = :cs, contract_end = :ce WHERE id = :id"),
            {"cs": effective_start, "ce": effective_end, "id": str(tenant_id)},
        )
        contract_start_out = str(effective_start)
        contract_end_out = str(effective_end)
    else:
        contract_start_out = str(subscription_result["current_period_start"])
        contract_end_out = str(subscription_result["current_period_end"])

    # Atomic TA admin user creation — same DB transaction as tenant INSERT.
    admin_user_id: Optional[uuid.UUID] = None
    admin_email_out: Optional[str] = None
    if body.admin_email and body.admin_password:
        import bcrypt as _bcrypt

        pw_hash = _bcrypt.hashpw(body.admin_password.encode(), _bcrypt.gensalt()).decode()
        admin_user_id = uuid.uuid4()
        normalized_admin_email = body.admin_email.strip().lower()
        admin_email_out = normalized_admin_email

        # Email is globally unique (uq_users_email_lower, migration 070) —
        # check across ALL tenants, never reveal which tenant owns it.
        existing = (
            await db.execute(
                text("SELECT id FROM users WHERE lower(email) = :email"),
                {"email": normalized_admin_email},
            )
        ).fetchone()
        if existing:
            raise _duplicate_email_http_exception()

        try:
            await db.execute(
                text(
                    "INSERT INTO users "
                    "  (id, tenant_id, email, full_name, password_hash, "
                    "   is_active, must_reset_password, system_role, is_account_owner) "
                    "VALUES (:id, :tid, :email, :name, :hash, true, true, 'TA', true)"
                ),
                {
                    "id": str(admin_user_id),
                    "tid": str(tenant_id),
                    "email": normalized_admin_email,
                    "name": body.admin_name or body.admin_email,
                    "hash": pw_hash,
                },
            )
        except IntegrityError as exc:
            if _is_duplicate_email_violation(exc):
                raise _duplicate_email_http_exception() from exc
            raise

    return SuccessResponse(
        data=TenantResponse(
            id=tenant_id,
            name=body.name,
            slug=slug,
            organisation_type=body.organisation_type,
            onboarding_complete=False,
            default_locale=body.default_locale,
            is_active=True,
            plan_tier=body.plan_tier,
            contract_start=contract_start_out,
            contract_end=contract_end_out,
            admin_user_id=admin_user_id,
            admin_email=admin_email_out,
        )
    )


async def _get_tenant_plan_data(db: AsyncSession, tenant_id: uuid.UUID | str) -> dict:
    """Shared by GET /me/plan (TA) and GET /{tenant_id}/plan (SA) — same shape.
    plan_tier is None, never a hardcoded tier, when the tenant has none set (CLAUDE.md §15).
    feature_flags/addons come from get_tenant_entitlements() — the single source
    of a tenant's effective plan (package flags OR'd with active add-ons, S10)."""
    entitlements = await get_tenant_entitlements(db, str(tenant_id))
    if not entitlements:
        raise HTTPException(status_code=404, detail="Tenant not found")

    row = (
        await db.execute(
            text("SELECT contract_start, contract_end FROM tenants WHERE id = :tid"),
            {"tid": str(tenant_id)},
        )
    ).fetchone()
    return {
        "plan_tier": entitlements["plan_tier"],
        "feature_flags": entitlements["feature_flags"],
        "sku_cap": entitlements["sku_cap"],
        "max_warehouses": entitlements["max_warehouses"],
        "max_users": entitlements["max_users"],
        "addons": entitlements["addons"],
        "contract_start": str(row.contract_start) if row and row.contract_start else None,
        "contract_end": str(row.contract_end) if row and row.contract_end else None,
    }


@router.get("/me/plan", response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.TENANT_VIEW)
async def get_my_plan(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[dict]:
    """Return the current tenant's plan_tier and feature_flags.
    Used by the frontend to gate UI features."""
    if not user or not user.tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context")
    return SuccessResponse(data=await _get_tenant_plan_data(db, user.tenant_id))


@router.get("/me/plan-usage", response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.PLAN_VIEW_USAGE)
async def get_my_plan_usage(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[dict]:
    """Return the current tenant's plan_tier plus used/limit for skus, users,
    warehouses — shared/plans/usage.py's get_plan_usage(), the same counts
    that gate create_product / check_plan_create_user / check_plan_create_warehouse."""
    if not user or not user.tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context")
    usage = await get_plan_usage(db, str(user.tenant_id))
    if not usage:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return SuccessResponse(data=usage)


class TermsAcceptanceOut(BaseModel):
    accepted_version: Optional[str] = None
    accepted_at: Optional[str] = None
    accepted_by_email: Optional[str] = None
    current_version: str


async def _get_terms_acceptance(db: AsyncSession, tenant_id) -> TermsAcceptanceOut:
    """terms_acceptances is written only by public_signup.py (CLAUDE.md §15
    S4) — an SA-created tenant (POST /tenants/) never gets a row here, which
    is expected, not an error. Newest acceptance wins if a tenant somehow
    has more than one (it shouldn't, today)."""
    current_version = get_terms_version()
    row = (
        await db.execute(
            text(
                "SELECT ta.terms_version, ta.accepted_at, u.email "
                "FROM terms_acceptances ta JOIN users u ON u.id = ta.user_id "
                "WHERE ta.tenant_id = :tid ORDER BY ta.accepted_at DESC LIMIT 1"
            ),
            {"tid": str(tenant_id)},
        )
    ).fetchone()
    if not row:
        return TermsAcceptanceOut(current_version=current_version)
    return TermsAcceptanceOut(
        accepted_version=row.terms_version,
        accepted_at=row.accepted_at.isoformat() if row.accepted_at else None,
        accepted_by_email=row.email,
        current_version=current_version,
    )


@router.get("/me/terms-acceptance", response_model=SuccessResponse[TermsAcceptanceOut])
@require_permission(PERMISSIONS.TENANT_VIEW)
async def get_my_terms_acceptance(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TermsAcceptanceOut]:
    """TA: read-only terms-acceptance record for its own tenant."""
    if not user or not user.tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context")
    return SuccessResponse(data=await _get_terms_acceptance(db, user.tenant_id))


@router.post("/me/terms-acceptance", response_model=SuccessResponse[TermsAcceptanceOut])
@require_permission(PERMISSIONS.TENANT_CONFIGURE, read_only_exempt=True)
async def accept_current_terms(
    request: Request,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TermsAcceptanceOut]:
    """Account-owner-only: record acceptance of the CURRENT terms version for
    the caller's own tenant. Idempotent — a repeat call when the latest
    acceptance already matches the current version returns it unchanged
    rather than inserting a duplicate row."""
    if not user or not user.tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context")

    owner_row = (
        await db.execute(
            text("SELECT is_account_owner FROM users WHERE id = :uid"),
            {"uid": user.user_id},
        )
    ).fetchone()
    if not owner_row or not owner_row.is_account_owner:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "NOT_ACCOUNT_OWNER",
                "message": "Only the account owner can accept terms.",
            },
        )

    current = await _get_terms_acceptance(db, user.tenant_id)
    if current.accepted_version == current.current_version:
        return SuccessResponse(data=current)

    user_agent = (request.headers.get("User-Agent") or "")[:500]
    await db.execute(
        text(
            "INSERT INTO terms_acceptances (tenant_id, user_id, terms_version, ip_address, user_agent) "
            "VALUES (:tid, :uid, :tv, :ip, :ua)"
        ),
        {
            "tid": str(user.tenant_id),
            "uid": user.user_id,
            "tv": current.current_version,
            "ip": client_ip(request),
            "ua": user_agent,
        },
    )

    try:
        await _log_tenant_activity(
            db,
            user.tenant_id,
            user.user_id,
            action="TERMS_ACCEPTED",
            old_value=current.accepted_version,
            new_value=current.current_version,
        )
    except Exception:
        pass

    return SuccessResponse(data=await _get_terms_acceptance(db, user.tenant_id))


def _serialize_preview(preview: dict) -> dict:
    """proration.preview_upgrade()/preview_addon() return Decimal/date values
    — JSON-serialize them the same way every other response in this router
    does (str()), rather than relying on FastAPI's default encoder."""
    out = dict(preview)
    for key in ("old_amount", "new_amount", "subtotal", "vat", "total"):
        if out.get(key) is not None:
            out[key] = str(out[key])
    for key in ("free_until", "period_end"):
        if out.get(key) is not None:
            out[key] = out[key].isoformat()
    return out


class PlanUpdateRequest(BaseModel):
    plan_tier: str
    max_warehouses: Optional[int] = None  # if None, auto-set from platform_tier_config
    max_users: Optional[int] = None  # if None, auto-set from platform_tier_config
    sku_cap: Optional[int] = None  # None = unlimited; only updated when key present in body
    effective: Literal["RENEWAL", "IMMEDIATE"] = "RENEWAL"  # S13 — SA override with IMMEDIATE


# ── TA Self-Service Endpoints ────────────────────────────────────────────────


@router.get("/me/profile", response_model=SuccessResponse[TenantResponse])
@require_permission(PERMISSIONS.TENANT_VIEW)
async def get_my_profile(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TenantResponse]:
    """TA: get their own tenant profile. Mirrors SA /{tenant_id} endpoint."""
    if not user or not user.tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context")

    result = await db.execute(
        text("SELECT * FROM tenants WHERE id = :id"), {"id": str(user.tenant_id)}
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found")

    return SuccessResponse(
        data=TenantResponse(
            id=row.id,
            name=row.name,
            slug=getattr(row, "slug", None),
            organisation_type=row.organisation_type,
            onboarding_complete=row.onboarding_complete,
            default_locale=row.default_locale,
            is_active=row.is_active,
            status=getattr(row, "status", None),
            logo_url=getattr(row, "logo_url", None),
            banner_url=getattr(row, "banner_url", None),
            plan_tier=str(row.plan_tier) if getattr(row, "plan_tier", None) else None,
            max_warehouses=getattr(row, "max_warehouses", None),
            max_users=getattr(row, "max_users", None),
            contract_start=str(row.contract_start)
            if getattr(row, "contract_start", None)
            else None,
            contract_end=str(row.contract_end) if getattr(row, "contract_end", None) else None,
        )
    )


class ContractUpdateRequest(BaseModel):
    contract_start: Optional[str] = None  # "YYYY-MM-DD" or null to clear
    contract_end: Optional[str] = None  # "YYYY-MM-DD" or null to clear
    note: str  # required — mandatory audit reason


class TAProfileUpdateRequest(BaseModel):
    """TA can only update specific fields of their own profile."""

    default_locale: Optional[str] = None


# Package changes are SA-only (CLAUDE.md §15 S12) — any of these present in a
# PATCH /me/profile body is rejected before any write, even though
# TAProfileUpdateRequest has no field for them (Pydantic would otherwise just
# silently drop them). SA PATCH /{tenant_id}/plan and /{tenant_id}/profile
# are unaffected by this check.
PLAN_BILLING_FIELDS = {
    "plan_tier",
    "max_warehouses",
    "max_users",
    "sku_cap",
    "feature_flags",
    "billing_period",
}


@router.patch("/me/profile", response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.TENANT_CONFIGURE)
async def update_my_profile(
    request: Request,
    body: TAProfileUpdateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[dict]:
    """TA: update limited fields of their own tenant profile (locale only)."""
    if not user or not user.tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context")

    raw_body = await request.json()
    if isinstance(raw_body, dict) and PLAN_BILLING_FIELDS & raw_body.keys():
        raise HTTPException(
            status_code=403,
            detail={
                "code": "PLAN_CHANGE_SA_ONLY",
                "message": "Package changes are made by SMART. Contact your SMART administrator.",
            },
        )

    if body.default_locale is not None and body.default_locale not in VALID_LOCALES:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_LOCALE",
                "allowed": ", ".join(sorted(VALID_LOCALES)),
                "message": f"default_locale must be one of {sorted(VALID_LOCALES)}",
            },
        )

    if body.default_locale is None:
        return SuccessResponse(data={"changes": 0})

    old_locale = (
        await db.execute(
            text("SELECT default_locale FROM tenants WHERE id = :id"),
            {"id": str(user.tenant_id)},
        )
    ).scalar() or "en"

    if body.default_locale == old_locale:
        return SuccessResponse(data={"changes": 0})

    await db.execute(
        text("UPDATE tenants SET default_locale = :locale, updated_at = now() WHERE id = :id"),
        {"locale": body.default_locale, "id": str(user.tenant_id)},
    )

    try:
        await _log_tenant_activity(
            db,
            user.tenant_id,
            str(user.user_id),
            action="PROFILE_UPDATE",
            old_value=old_locale,
            new_value=body.default_locale,
        )
    except Exception:
        pass

    return SuccessResponse(data={"default_locale": body.default_locale})


@router.patch("/me/contract", response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.TENANT_CONTRACT_EDIT)
async def update_my_contract(
    body: ContractUpdateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[dict]:
    """TA: update their own contract with mandatory note for audit trail."""
    from datetime import date as _date

    if not user or not user.tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context")

    note = body.note.strip() if body.note else ""
    if not note:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "NOTE_REQUIRED",
                "message": "A note explaining the contract change is required.",
            },
        )

    row = (
        await db.execute(
            text("SELECT id, status, contract_start, contract_end FROM tenants WHERE id = :id"),
            {"id": str(user.tenant_id)},
        )
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found")

    def _parse_date(s: Optional[str], field: str) -> Optional[_date]:
        if s is None:
            return None
        try:
            return _date.fromisoformat(s)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "INVALID_DATE",
                    "field": field,
                    "message": f"'{s}' is not a valid ISO date (YYYY-MM-DD).",
                },
            )

    new_start = _parse_date(body.contract_start, "contract_start")
    new_end = _parse_date(body.contract_end, "contract_end")

    old_start = str(row.contract_start) if row.contract_start else None
    old_end = str(row.contract_end) if row.contract_end else None

    # Auto-reactivate if tenant was suspended and new end is in future
    should_reactivate = (
        str(row.status) == "SUSPENDED" and new_end is not None and new_end >= _date.today()
    )

    if not any(x for x in [new_start, new_end, should_reactivate] if x):
        return SuccessResponse(data={"changes": 0})

    set_parts = ["updated_at = now()"]
    params = {"id": str(user.tenant_id)}

    if body.contract_start is not None:
        set_parts.append("contract_start = :start")
        params["start"] = new_start

    if body.contract_end is not None:
        set_parts.append("contract_end = :end")
        set_parts.append("contract_expiry_notified = '[]'::jsonb")
        params["end"] = new_end

    if should_reactivate:
        set_parts.append("status = 'ACTIVE'")
        set_parts.append("is_active = true")

    await db.execute(
        text(f"UPDATE tenants SET {', '.join(set_parts)} WHERE id = :id"),
        params,
    )

    try:
        await _log_tenant_activity(
            db,
            user.tenant_id,
            str(user.user_id),
            action="CONTRACT_RENEWAL",
            old_value=f"start:{old_start}, end:{old_end}",
            new_value=f"start:{body.contract_start}, end:{body.contract_end}",
            note=note,
        )
    except Exception:
        pass

    return SuccessResponse(
        data={
            "contract_start": body.contract_start,
            "contract_end": body.contract_end,
            "reactivated": should_reactivate,
        }
    )


@router.get("/me/contract-status", response_model=SuccessResponse[ContractStatusOut])
@require_permission(PERMISSIONS.TENANT_VIEW_CONTRACT_STATUS)
async def get_my_contract_status(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[ContractStatusOut]:
    """TA and tenant staff: this tenant's current contract stage, plus any
    OPEN renewal request already on file."""
    if not user or not user.tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context")

    stage_info = await get_tenant_contract_stage(db, str(user.tenant_id))
    contract_end = stage_info["contract_end"]
    today = datetime.utcnow().date()
    days_left = (contract_end - today).days if contract_end else None

    open_row = (
        await db.execute(
            text(
                "SELECT id, created_at FROM tenant_renewal_requests "
                "WHERE tenant_id = :tid AND status = 'OPEN' AND request_type = 'RENEWAL' "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"tid": str(user.tenant_id)},
        )
    ).fetchone()
    open_request = (
        ContractStatusOpenRequest(id=open_row.id, created_at=open_row.created_at.isoformat())
        if open_row
        else None
    )

    return SuccessResponse(
        data=ContractStatusOut(
            stage=stage_info["stage"],
            contract_end=str(contract_end) if contract_end else None,
            days_left=days_left,
            grace_ends=str(stage_info["grace_ends"]) if stage_info["grace_ends"] else None,
            read_only_since=(
                str(stage_info["read_only_since"]) if stage_info["read_only_since"] else None
            ),
            open_request=open_request,
        )
    )


@router.post(
    "/me/renewal-requests", status_code=201, response_model=SuccessResponse[RenewalRequestOut]
)
@require_permission(PERMISSIONS.TENANT_RENEWAL_REQUEST)
async def create_my_renewal_request(
    body: RenewalRequestIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[RenewalRequestOut]:
    """TA: request a contract renewal or upgrade. Allowed at ANY contract
    stage (the action is in read_only.ALLOWED_WRITE_ACTIONS) — one OPEN
    request per (tenant, request_type) at a time; a second attempt on the
    same type returns the existing request's id."""
    if not user or not user.tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context")

    if body.request_type == "UPGRADE" and body.requested_tier is None:
        raise HTTPException(status_code=422, detail={"code": "REQUESTED_TIER_REQUIRED"})
    if body.request_type == "RENEWAL" and body.requested_tier is not None:
        raise HTTPException(status_code=422, detail={"code": "REQUESTED_TIER_NOT_ALLOWED"})

    if body.request_type == "UPGRADE":
        tenant_row = (
            await db.execute(
                text("SELECT plan_tier FROM tenants WHERE id = :tid"),
                {"tid": str(user.tenant_id)},
            )
        ).fetchone()
        current_tier = str(tenant_row.plan_tier) if tenant_row and tenant_row.plan_tier else None
        if current_tier not in _VALID_TIERS or _VALID_TIERS.index(
            body.requested_tier
        ) <= _VALID_TIERS.index(current_tier):
            raise HTTPException(status_code=422, detail={"code": "NOT_AN_UPGRADE"})

    existing = (
        await db.execute(
            text(
                "SELECT id FROM tenant_renewal_requests "
                "WHERE tenant_id = :tid AND request_type = :rtype AND status = 'OPEN'"
            ),
            {"tid": str(user.tenant_id), "rtype": body.request_type},
        )
    ).fetchone()
    if existing:
        open_code = (
            "RENEWAL_REQUEST_OPEN" if body.request_type == "RENEWAL" else "UPGRADE_REQUEST_OPEN"
        )
        raise HTTPException(
            status_code=409,
            detail={"code": open_code, "id": str(existing.id)},
        )

    email_row = (
        await db.execute(
            text("SELECT email FROM users WHERE id = :uid LIMIT 1"),
            {"uid": str(user.user_id)},
        )
    ).fetchone()
    requested_by_email = email_row.email if email_row else None

    row = (
        await db.execute(
            text(
                "INSERT INTO tenant_renewal_requests "
                "(tenant_id, requested_by, requested_by_email, message, request_type, requested_tier) "
                "VALUES (:tid, :uid, :email, :message, :rtype, :rtier) "
                "RETURNING id, tenant_id, requested_by, requested_by_email, message, "
                "request_type, requested_tier, status, handled_by, handled_note, handled_at, created_at"
            ),
            {
                "tid": str(user.tenant_id),
                "uid": str(user.user_id),
                "email": requested_by_email,
                "message": body.message,
                "rtype": body.request_type,
                "rtier": body.requested_tier,
            },
        )
    ).fetchone()

    action = "RENEWAL_REQUESTED" if body.request_type == "RENEWAL" else "UPGRADE_REQUESTED"
    await _log_tenant_activity(
        db,
        user.tenant_id,
        str(user.user_id),
        action=action,
        new_value=body.requested_tier if body.request_type == "UPGRADE" else None,
        note=body.message,
    )

    # SA email delivery comes later with SES — for now, surface in the logs.
    log_label = "RenewalRequested" if body.request_type == "RENEWAL" else "UpgradeRequested"
    logger.warning("%s tenant=%s by=%s", log_label, user.tenant_id, user.user_id)

    return SuccessResponse(data=_renewal_row_to_out(row))


@router.get("/me/renewal-requests", response_model=SuccessResponse[List[RenewalRequestOut]])
@require_permission(PERMISSIONS.TENANT_RENEWAL_REQUEST)
async def list_my_renewal_requests(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[List[RenewalRequestOut]]:
    """TA: the 10 most recent renewal requests for their own tenant."""
    if not user or not user.tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context")

    rows = (
        await db.execute(
            text(
                "SELECT id, tenant_id, requested_by, requested_by_email, message, "
                "request_type, requested_tier, status, handled_by, handled_note, handled_at, created_at "
                "FROM tenant_renewal_requests WHERE tenant_id = :tid "
                "ORDER BY created_at DESC LIMIT 10"
            ),
            {"tid": str(user.tenant_id)},
        )
    ).fetchall()

    return SuccessResponse(data=[_renewal_row_to_out(r) for r in rows])


@router.get("/me/contacts", response_model=SuccessResponse[List[TenantContactOut]])
@require_permission(PERMISSIONS.TENANT_VIEW)
async def get_my_contacts(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[List[TenantContactOut]]:
    """TA: get their own tenant's contacts."""
    if not user or not user.tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context")

    rows = (
        await db.execute(
            text(
                "SELECT id, tenant_id, is_primary, full_name, position_title, "
                "email, phone, mobile, created_at "
                "FROM tenant_contacts WHERE tenant_id = :tid "
                "ORDER BY is_primary DESC, created_at ASC"
            ),
            {"tid": str(user.tenant_id)},
        )
    ).fetchall()

    return SuccessResponse(
        data=[
            TenantContactOut(
                id=row.id,
                tenant_id=row.tenant_id,
                is_primary=row.is_primary,
                full_name=row.full_name,
                position_title=row.position_title,
                email=row.email,
                phone=row.phone,
                mobile=row.mobile,
                created_at=row.created_at.isoformat(),
            )
            for row in rows
        ]
    )


async def _create_tenant_contact(
    db: AsyncSession,
    tenant_id: uuid.UUID | str,
    body: TenantContactIn,
) -> TenantContactOut:
    """Shared by POST /me/contacts (TA) and POST /{tenant_id}/contacts (SA)."""
    from datetime import datetime

    if not body.full_name or not body.full_name.strip():
        raise HTTPException(status_code=422, detail="full_name is required")

    contact_id = uuid.uuid4()
    now_dt = datetime.utcnow()

    await db.execute(
        text(
            "INSERT INTO tenant_contacts "
            "(id, tenant_id, is_primary, full_name, position_title, email, phone, mobile, created_at) "
            "VALUES (:id, :tid, :primary, :name, :title, :email, :phone, :mobile, :now)"
        ),
        {
            "id": contact_id,
            "tid": str(tenant_id),
            "primary": body.is_primary,
            "name": body.full_name.strip(),
            "title": body.position_title,
            "email": body.email,
            "phone": body.phone,
            "mobile": body.mobile,
            "now": now_dt,
        },
    )
    await db.commit()

    return TenantContactOut(
        id=contact_id,
        tenant_id=tenant_id,
        is_primary=body.is_primary,
        full_name=body.full_name.strip(),
        position_title=body.position_title,
        email=body.email,
        phone=body.phone,
        mobile=body.mobile,
        created_at=now_dt.isoformat(),
    )


async def _update_tenant_contact(
    db: AsyncSession,
    tenant_id: uuid.UUID | str,
    contact_id: uuid.UUID,
    body: TenantContactIn,
) -> TenantContactOut:
    """Shared by PATCH /me/contacts/{id} (TA) and PATCH /{tenant_id}/contacts/{id} (SA).
    Raises 404 if the contact does not belong to tenant_id."""
    if not body.full_name or not body.full_name.strip():
        raise HTTPException(status_code=422, detail="full_name is required")

    row = (
        await db.execute(
            text(
                "SELECT id, tenant_id, is_primary, full_name, position_title, "
                "email, phone, mobile, created_at "
                "FROM tenant_contacts WHERE id = :id AND tenant_id = :tid"
            ),
            {"id": contact_id, "tid": str(tenant_id)},
        )
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Contact not found")

    await db.execute(
        text(
            "UPDATE tenant_contacts SET "
            "is_primary = :primary, full_name = :name, position_title = :title, "
            "email = :email, phone = :phone, mobile = :mobile "
            "WHERE id = :id AND tenant_id = :tid"
        ),
        {
            "id": contact_id,
            "tid": str(tenant_id),
            "primary": body.is_primary,
            "name": body.full_name.strip(),
            "title": body.position_title,
            "email": body.email,
            "phone": body.phone,
            "mobile": body.mobile,
        },
    )
    await db.commit()

    return TenantContactOut(
        id=contact_id,
        tenant_id=tenant_id,
        is_primary=body.is_primary,
        full_name=body.full_name.strip(),
        position_title=body.position_title,
        email=body.email,
        phone=body.phone,
        mobile=body.mobile,
        created_at=row.created_at.isoformat(),
    )


@router.post("/me/contacts", status_code=201, response_model=SuccessResponse[TenantContactOut])
@require_permission(PERMISSIONS.TENANT_CONFIGURE, read_only_exempt=True)
async def create_my_contact(
    body: TenantContactIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TenantContactOut]:
    """TA: create a contact for their own tenant."""
    if not user or not user.tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context")
    return SuccessResponse(data=await _create_tenant_contact(db, user.tenant_id, body))


@router.patch("/me/contacts/{contact_id}", response_model=SuccessResponse[TenantContactOut])
@require_permission(PERMISSIONS.TENANT_CONFIGURE, read_only_exempt=True)
async def update_my_contact(
    contact_id: uuid.UUID,
    body: TenantContactIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TenantContactOut]:
    """TA: update a contact in their own tenant."""
    if not user or not user.tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context")
    return SuccessResponse(data=await _update_tenant_contact(db, user.tenant_id, contact_id, body))


@router.delete("/me/contacts/{contact_id}", status_code=204)
@require_permission(PERMISSIONS.TENANT_CONFIGURE, read_only_exempt=True)
async def delete_my_contact(
    contact_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """TA: delete a contact from their own tenant."""
    if not user or not user.tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context")

    result = await db.execute(
        text("DELETE FROM tenant_contacts WHERE id = :id AND tenant_id = :tid"),
        {"id": contact_id, "tid": str(user.tenant_id)},
    )
    await db.commit()

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Contact not found")

    return Response(status_code=204)


@router.get("/{tenant_id}/plan", response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.TENANT_MANAGE, read_only_exempt=True)
async def get_tenant_plan(
    tenant_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[dict]:
    """SA-only: same data/shape as GET /me/plan, for any tenant."""
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})
    return SuccessResponse(data=await _get_tenant_plan_data(db, tenant_id))


@router.get("/{tenant_id}/terms-acceptance", response_model=SuccessResponse[TermsAcceptanceOut])
@require_permission(PERMISSIONS.TENANT_MANAGE, read_only_exempt=True)
async def get_tenant_terms_acceptance(
    tenant_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TermsAcceptanceOut]:
    """SA-only: same data/shape as GET /me/terms-acceptance, for any tenant."""
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})
    return SuccessResponse(data=await _get_terms_acceptance(db, tenant_id))


@router.get("/{tenant_id}/proration-preview", response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.TENANT_MANAGE, read_only_exempt=True)
async def get_tenant_proration_preview(
    tenant_id: uuid.UUID,
    tier: Optional[str] = None,
    addon: Optional[str] = None,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[dict]:
    """SA-only: same preview as GET /me/proration-preview, for any tenant."""
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})
    if bool(tier) == bool(addon):
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_REQUEST", "message": "Pass exactly one of tier or addon"},
        )
    preview = await (
        preview_upgrade(db, str(tenant_id), tier)
        if tier
        else preview_addon(db, str(tenant_id), addon)
    )
    return SuccessResponse(data=_serialize_preview(preview))


@router.patch("/{tenant_id}/plan", response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.TENANT_MANAGE)
async def update_tenant_plan(
    tenant_id: uuid.UUID,
    body: PlanUpdateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[dict]:
    """SA-only: update a tenant's plan tier and resource caps."""
    if not user or user.role != "SA":
        raise HTTPException(
            status_code=403,
            detail={"code": "FORBIDDEN", "message": "SA only"},
        )
    valid_tiers = {"STARTER", "GROWTH", "ENTERPRISE"}
    if body.plan_tier not in valid_tiers:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_TIER",
                "message": f"plan_tier must be one of {sorted(valid_tiers)}",
            },
        )
    old_row = (
        await db.execute(
            text("SELECT plan_tier FROM tenants WHERE id = :id"),
            {"id": str(tenant_id)},
        )
    ).fetchone()
    old_tier = str(old_row.plan_tier) if old_row and old_row.plan_tier else None

    # A paid downgrade defaults to SCHEDULE-at-renewal (S13) — nothing else
    # changes now. effective="IMMEDIATE" is the SA override for today's
    # immediate behaviour. An ANNUAL upgrade that has already been paid at
    # least once also raises a PRORATION invoice for the whole remaining
    # billing months on the IMMEDIATE path (CLAUDE.md §15 S11).
    try:
        plan_change = await change_plan(
            db,
            tenant_id,
            body.plan_tier,
            effective=body.effective,
            recorded_by=str(user.user_id),
            max_warehouses=body.max_warehouses
            if "max_warehouses" in body.model_fields_set
            else UNSET,
            max_users=body.max_users if "max_users" in body.model_fields_set else UNSET,
            sku_cap=body.sku_cap if "sku_cap" in body.model_fields_set else UNSET,
        )
    except ValueError as exc:
        code = str(exc)
        status_code = 409 if code == "INVOICE_PENDING_SETTLE_FIRST" else 422
        raise HTTPException(
            status_code=status_code,
            detail={"code": code, "message": str(exc)},
        ) from exc

    mode = plan_change["mode"]
    proration_invoice = plan_change.get("proration_invoice")
    subscription_change = plan_change.get("subscription_change")
    if mode == "IMMEDIATE" and subscription_change is None:
        logger.warning(
            "update_tenant_plan: no live subscription for tenant %s — not created here", tenant_id
        )

    try:
        if mode == "SCHEDULED":
            await _log_tenant_activity(
                db,
                tenant_id,
                str(user.user_id),
                action="PLAN_DOWNGRADE_SCHEDULED",
                old_value=plan_change["plan_tier"],
                new_value=plan_change["scheduled_tier"],
            )
        else:
            await _log_tenant_activity(
                db,
                tenant_id,
                str(user.user_id),
                action="PLAN_CHANGE",
                old_value=old_tier,
                new_value=body.plan_tier,
            )
            if mode == "UNCHANGED" and plan_change.get("scheduled_cleared"):
                await _log_tenant_activity(
                    db,
                    tenant_id,
                    str(user.user_id),
                    action="PLAN_DOWNGRADE_CANCELLED",
                    old_value=body.plan_tier,
                )
            if subscription_change is not None:
                await _log_tenant_activity(
                    db,
                    tenant_id,
                    str(user.user_id),
                    action="SUBSCRIPTION_TIER_CHANGE",
                    old_value=f"{subscription_change['old_tier']}/{subscription_change['old_amount']}",
                    new_value=f"{subscription_change['new_tier']}/{subscription_change['new_amount']}",
                )
            if proration_invoice is not None:
                await _log_tenant_activity(
                    db,
                    tenant_id,
                    str(user.user_id),
                    action="PRORATION_INVOICE_RAISED",
                    new_value=f"payment={proration_invoice['payment_id']} total={proration_invoice['total']}",
                )
    except Exception:
        pass  # log failure must not roll back the plan change

    effective_package = plan_change.get("effective")
    if effective_package is None:
        # SCHEDULED / UNCHANGED — nothing was applied; show the tenant's current values.
        current = await get_tenant_entitlements(db, tenant_id)
        plan_tier_out = plan_change.get("plan_tier", current.get("plan_tier"))
        max_wh_out = current.get("max_warehouses")
        max_u_out = current.get("max_users")
    else:
        plan_tier_out = effective_package["plan_tier"]
        max_wh_out = effective_package["max_warehouses"]
        max_u_out = effective_package["max_users"]

    return SuccessResponse(
        data={
            "mode": mode,
            "plan_tier": plan_tier_out,
            "max_warehouses": max_wh_out,
            "max_users": max_u_out,
            "proration_invoice": proration_invoice,
            "scheduled_tier": plan_change.get("scheduled_tier"),
            "effective_at": plan_change.get("effective_at"),
            "pending_renewal_invoice_id": plan_change.get("pending_renewal_invoice_id"),
        }
    )


@router.delete("/{tenant_id}/plan/scheduled", response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.TENANT_MANAGE)
async def cancel_tenant_scheduled_downgrade(
    tenant_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[dict]:
    """SA-only: cancel a pending scheduled downgrade (S13) — the tenant
    keeps its current tier at the next renewal."""
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})

    try:
        result = await cancel_scheduled_downgrade(db, tenant_id)
    except ValueError as exc:
        code = str(exc)
        status_code = 404 if code == "NO_SCHEDULED_CHANGE" else 422
        raise HTTPException(
            status_code=status_code,
            detail={"code": code, "message": str(exc)},
        ) from exc

    try:
        await _log_tenant_activity(
            db,
            tenant_id,
            str(user.user_id),
            action="PLAN_DOWNGRADE_CANCELLED",
            old_value=result["cancelled_tier"],
        )
    except Exception:
        pass  # log failure must not roll back the cancellation

    return SuccessResponse(data=result)


class TenantProfileUpdateRequest(BaseModel):
    name: Optional[str] = None
    organisation_type: Optional[str] = None
    default_locale: Optional[str] = None
    plan_tier: Optional[str] = None
    notes: Optional[str] = None
    industry: Optional[str] = None
    # Company address — all fields updated atomically when any is provided
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state_province: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None


VALID_LOCALES = frozenset({"en", "am", "or"})

_PROFILE_ADDR_FIELDS = (
    "address_line1",
    "address_line2",
    "city",
    "state_province",
    "postal_code",
    "country",
)


def _build_profile_update_set_clause(
    changes: dict[str, tuple[str | None, str | None]],
    body: TenantProfileUpdateRequest,
) -> tuple[list[str], dict]:
    """Pure: build the SET clause + params for update_tenant_profile from the
    already-computed `changes` map — everything EXCEPT plan_tier, which needs
    an async package lookup via apply_package_to_tenant and is handled by the
    caller. Org-type change sets approval_thresholds only — feature flags are
    owned by the plan/package (CLAUDE.md §15) and are never touched here.
    """
    set_parts: list[str] = ["updated_at = now()"]
    params: dict = {}

    if "name" in changes:
        set_parts.append("name = :name")
        params["name"] = changes["name"][1]

    if "organisation_type" in changes:
        new_org = changes["organisation_type"][1]
        set_parts.append("organisation_type = CAST(:org_type AS organisation_type)")
        params["org_type"] = new_org
        set_parts.append("approval_thresholds = CAST(:thresholds AS jsonb)")
        params["thresholds"] = json.dumps(APPROVAL_DEFAULTS.get(new_org, {}))

    if "default_locale" in changes:
        set_parts.append("default_locale = :locale")
        params["locale"] = changes["default_locale"][1]

    if "notes" in changes:
        set_parts.append("notes = :notes")
        params["notes"] = changes["notes"][1]

    if "industry" in changes:
        set_parts.append("industry = :industry")
        params["industry"] = changes["industry"][1]

    if "address" in changes:
        for f in _PROFILE_ADDR_FIELDS:
            set_parts.append(f"{f} = :{f}")
            params[f] = getattr(body, f)

    return set_parts, params


@router.patch("/{tenant_id}/profile", response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.TENANT_PROFILE_EDIT)
async def update_tenant_profile(
    tenant_id: uuid.UUID,
    body: TenantProfileUpdateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[dict]:
    """SA-only: re-edit wizard-configurable tenant profile fields with full audit trail.

    When organisation_type changes, only approval_thresholds reset to the new
    type's defaults — feature flags are owned by the plan/package, not org type.
    When plan_tier changes, it goes through change_plan() (S13, effective=
    RENEWAL always here) — same as update_tenant_plan does for SA PATCH /plan.
    """
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})

    row = (
        await db.execute(
            text(
                "SELECT id, name, organisation_type, default_locale, plan_tier, "
                "notes, industry, address_line1, address_line2, city, state_province, postal_code, country "
                "FROM tenants WHERE id = :id"
            ),
            {"id": str(tenant_id)},
        )
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Validate supplied values before touching the DB
    if (
        body.organisation_type is not None
        and body.organisation_type not in VALID_ORGANISATION_TYPES
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_ORGANISATION_TYPE",
                "message": f"organisation_type must be one of {sorted(VALID_ORGANISATION_TYPES)}",
            },
        )
    if body.default_locale is not None and body.default_locale not in VALID_LOCALES:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_LOCALE",
                "allowed": ", ".join(sorted(VALID_LOCALES)),
                "message": f"default_locale must be one of {sorted(VALID_LOCALES)}",
            },
        )
    if body.plan_tier is not None and body.plan_tier not in VALID_PLAN_TIERS:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_TIER",
                "message": f"plan_tier must be one of {sorted(VALID_PLAN_TIERS)}",
            },
        )

    # Compute which fields actually changed so we only write and log real deltas.
    old_name = row.name
    old_org_type = str(row.organisation_type) if row.organisation_type else None
    old_locale = row.default_locale or "en"
    old_tier = str(row.plan_tier) if row.plan_tier else None

    changes: dict[str, tuple[str | None, str | None]] = {}
    if body.name is not None and body.name.strip() and body.name.strip() != old_name:
        changes["name"] = (old_name, body.name.strip())
    if body.organisation_type is not None and body.organisation_type != old_org_type:
        changes["organisation_type"] = (old_org_type, body.organisation_type)
    if body.default_locale is not None and body.default_locale != old_locale:
        changes["default_locale"] = (old_locale, body.default_locale)
    if body.plan_tier is not None and body.plan_tier != old_tier:
        changes["plan_tier"] = (old_tier, body.plan_tier)
    if "notes" in body.model_fields_set and body.notes != row.notes:
        changes["notes"] = (row.notes, body.notes)
    if "industry" in body.model_fields_set and body.industry != getattr(row, "industry", None):
        changes["industry"] = (getattr(row, "industry", None), body.industry)

    # Address — treated as one atomic block; log as single entry if any field changed
    addr_provided = any(f in body.model_fields_set for f in _PROFILE_ADDR_FIELDS)
    addr_changed = addr_provided and any(
        getattr(body, f) != getattr(row, f) for f in _PROFILE_ADDR_FIELDS
    )
    if addr_changed:
        changes["address"] = (
            f"{row.address_line1 or ''}, {row.city or ''}, {row.country or ''}".strip(", "),
            f"{body.address_line1 or ''}, {body.city or ''}, {body.country or ''}".strip(", "),
        )

    if not changes:
        return SuccessResponse(data={"changes": 0, "fields": []})

    # Build SET clause for everything except plan_tier via the pure helper.
    set_parts, params = _build_profile_update_set_clause(changes, body)
    params["id"] = str(tenant_id)
    await db.execute(
        text(f"UPDATE tenants SET {', '.join(set_parts)} WHERE id = :id"),
        params,
    )

    # plan_tier goes through change_plan (S13) — a paid downgrade SCHEDULEs
    # at the next renewal; anything else (upgrade, same-tier cap override,
    # never-paid downgrade) applies immediately via the package catalog,
    # which REPLACES feature_flags with the package's full flag set
    # (CLAUDE.md §15), plus the S11 proration invoice for an ANNUAL,
    # already-paid upgrade. No live subscription -> log a warning, don't
    # create one. This profile endpoint has no "effective" override — always
    # RENEWAL (SA uses PATCH /{tenant_id}/plan for an IMMEDIATE downgrade).
    plan_mode = None
    subscription_change = None
    proration_invoice = None
    if "plan_tier" in changes:
        new_tier = changes["plan_tier"][1]
        try:
            plan_change = await change_plan(
                db,
                tenant_id,
                new_tier,
                effective="RENEWAL",
                recorded_by=str(user.user_id),
            )
        except ValueError as exc:
            code = str(exc)
            status_code = 409 if code == "INVOICE_PENDING_SETTLE_FIRST" else 422
            raise HTTPException(
                status_code=status_code,
                detail={"code": code, "message": str(exc)},
            ) from exc
        plan_mode = plan_change["mode"]
        subscription_change = plan_change.get("subscription_change")
        proration_invoice = plan_change.get("proration_invoice")
        if plan_mode == "IMMEDIATE" and subscription_change is None:
            logger.warning(
                "update_tenant_profile: no live subscription for tenant %s — not created here",
                tenant_id,
            )

    # Log each changed field as its own activity row so the audit trail is granular.
    # plan_tier is skipped here when nothing was actually applied (SCHEDULED
    # logs its own PLAN_DOWNGRADE_SCHEDULED below; UNCHANGED means the live
    # subscription's tier already matched, so there is nothing to report).
    for field, (old_val, new_val) in changes.items():
        if field == "plan_tier" and plan_mode in ("SCHEDULED", "UNCHANGED"):
            continue
        try:
            await _log_tenant_activity(
                db,
                tenant_id,
                str(user.user_id),
                action=f"PROFILE_UPDATE_{field.upper()}",
                old_value=old_val,
                new_value=new_val,
            )
        except Exception:
            pass  # log failure must not roll back the update

    if subscription_change is not None:
        try:
            await _log_tenant_activity(
                db,
                tenant_id,
                str(user.user_id),
                action="SUBSCRIPTION_TIER_CHANGE",
                old_value=f"{subscription_change['old_tier']}/{subscription_change['old_amount']}",
                new_value=f"{subscription_change['new_tier']}/{subscription_change['new_amount']}",
            )
        except Exception:
            pass  # log failure must not roll back the update

    if proration_invoice is not None:
        try:
            await _log_tenant_activity(
                db,
                tenant_id,
                str(user.user_id),
                action="PRORATION_INVOICE_RAISED",
                new_value=f"payment={proration_invoice['payment_id']} total={proration_invoice['total']}",
            )
        except Exception:
            pass  # log failure must not roll back the update

    if plan_mode == "SCHEDULED":
        try:
            await _log_tenant_activity(
                db,
                tenant_id,
                str(user.user_id),
                action="PLAN_DOWNGRADE_SCHEDULED",
                old_value=changes["plan_tier"][0],
                new_value=changes["plan_tier"][1],
            )
        except Exception:
            pass  # log failure must not roll back the update

    reported_fields = [
        f for f in changes if not (f == "plan_tier" and plan_mode in ("SCHEDULED", "UNCHANGED"))
    ]
    return SuccessResponse(
        data={
            "changes": len(reported_fields),
            "fields": reported_fields,
            "proration_invoice": proration_invoice,
            "mode": plan_mode,
        }
    )


@router.get("/{tenant_id}", response_model=SuccessResponse[TenantResponse])
@require_permission(PERMISSIONS.TENANT_VIEW)
async def get_tenant(
    tenant_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TenantResponse]:
    from sqlalchemy import text

    resolved_id = await _resolve_and_authorize_tenant_id(tenant_id, user, db)
    result = await db.execute(text("SELECT * FROM tenants WHERE id = :id"), {"id": resolved_id})
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return SuccessResponse(
        data=TenantResponse(
            id=row.id,
            name=row.name,
            slug=getattr(row, "slug", None),
            organisation_type=row.organisation_type,
            onboarding_complete=row.onboarding_complete,
            default_locale=row.default_locale,
            is_active=row.is_active,
            status=getattr(row, "status", None),
            logo_url=getattr(row, "logo_url", None),
            banner_url=getattr(row, "banner_url", None),
            plan_tier=str(row.plan_tier) if getattr(row, "plan_tier", None) else None,
            max_warehouses=getattr(row, "max_warehouses", None),
            max_users=getattr(row, "max_users", None),
            contract_start=str(row.contract_start)
            if getattr(row, "contract_start", None)
            else None,
            contract_end=str(row.contract_end) if getattr(row, "contract_end", None) else None,
        )
    )


# ── Branding PATCH ─────────────────────────────────────────────────────────────


class BrandingUpdateRequest(BaseModel):
    logo_url: Optional[str] = None
    banner_url: Optional[str] = None


@router.patch("/{tenant_id}/branding", response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.TENANT_UPLOAD_BRANDING)
async def update_tenant_branding(
    tenant_id: str,
    body: BrandingUpdateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[dict]:
    """Persist logo_url / banner_url after an upload."""
    resolved_id = await _resolve_tenant_id(tenant_id, db)
    if not resolved_id:
        raise HTTPException(status_code=404, detail="Tenant not found")

    set_clauses = ["updated_at = NOW()"]
    params: dict = {"id": resolved_id}
    if body.logo_url is not None:
        set_clauses.append("logo_url = :logo_url")
        params["logo_url"] = body.logo_url
    if body.banner_url is not None:
        set_clauses.append("banner_url = :banner_url")
        params["banner_url"] = body.banner_url

    if len(set_clauses) > 1:
        await db.execute(
            text(f"UPDATE tenants SET {', '.join(set_clauses)} WHERE id = :id"),
            params,
        )

    row = (
        await db.execute(
            text("SELECT logo_url, banner_url FROM tenants WHERE id = :id"), {"id": resolved_id}
        )
    ).fetchone()
    return SuccessResponse(
        data={
            "logo_url": row.logo_url if row else None,
            "banner_url": row.banner_url if row else None,
        }
    )


# ── Approval rules schemas ─────────────────────────────────────────────────────


class ApprovalRuleItem(BaseModel):
    transaction_type: str
    min_quantity: Optional[float] = None
    max_quantity: Optional[float] = None
    approver_role: str
    authority_level: int = 1
    approval_order: int = 1
    auto_approve: bool = False
    notify_levels: List[int] = []


class ApprovalRulesBody(BaseModel):
    simple_mode: bool = True
    rules: List[ApprovalRuleItem]


async def _resolve_tenant_id(tenant_id: str, db: AsyncSession) -> Optional[str]:
    """Accept either a UUID or slug, return the UUID string or None if not found."""
    from sqlalchemy import text

    try:
        uuid.UUID(tenant_id)
        row = await db.execute(text("SELECT id FROM tenants WHERE id = :id"), {"id": tenant_id})
    except ValueError:
        row = await db.execute(
            text("SELECT id FROM tenants WHERE slug = :slug"), {"slug": tenant_id}
        )
    r = row.fetchone()
    return str(r.id) if r else None


async def _resolve_and_authorize_tenant_id(tenant_id: str, user, db: AsyncSession) -> str:
    """Resolve a UUID-or-slug path value to the real tenant id, then enforce the
    same cross-tenant-isolation contract as dependencies.get_db_session_for_tenant:
    SA may access any tenant; everyone else may only access their own.

    Raises 404 if the tenant doesn't exist, 403 TENANT_ACCESS_DENIED if a non-SA
    caller's own tenant_id doesn't match the resolved id (by UUID or by slug).
    """
    resolved_id = await _resolve_tenant_id(tenant_id, db)
    if not resolved_id:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if not user:
        raise HTTPException(status_code=401, detail="Unauthenticated")
    if user.role != "SA":
        if user.tenant_id is None or str(user.tenant_id) != resolved_id:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "TENANT_ACCESS_DENIED",
                    "message": "You do not have access to this tenant",
                },
            )
    return resolved_id


@router.get("/{tenant_id}/approval-rules", response_model=SuccessResponse[List[ApprovalRuleItem]])
@require_permission(PERMISSIONS.TENANT_VIEW)
async def get_approval_rules(
    tenant_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[List[ApprovalRuleItem]]:
    from sqlalchemy import text

    resolved_id = await _resolve_and_authorize_tenant_id(tenant_id, user, db)
    result = await db.execute(
        text("SELECT approval_thresholds FROM tenants WHERE id = :id"), {"id": resolved_id}
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found")
    raw = row.approval_thresholds or []
    if isinstance(raw, dict):
        if "rules" in raw:
            # New format: {"simple_mode": bool, "rules": [...]}
            rules_list = raw.get("rules", [])
        else:
            # Legacy {tx_type: {low, medium}} format → return empty, frontend pre-populates
            rules_list = []
    else:
        # Previous interim format: bare array
        rules_list = raw
    rules = [ApprovalRuleItem(**item) for item in rules_list]
    return SuccessResponse(data=rules)


@router.put("/{tenant_id}/approval-rules", response_model=SuccessResponse[List[ApprovalRuleItem]])
@require_permission(PERMISSIONS.TENANT_MANAGE)
async def put_approval_rules(
    tenant_id: str,
    body: ApprovalRulesBody,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[List[ApprovalRuleItem]]:
    from sqlalchemy import text

    resolved_id = await _resolve_and_authorize_tenant_id(tenant_id, user, db)
    payload = {
        "simple_mode": body.simple_mode,
        "rules": [rule.model_dump() for rule in body.rules],
    }
    await db.execute(
        text(
            "UPDATE tenants SET approval_thresholds = cast(:thresholds as jsonb), updated_at = now() "
            "WHERE id = :id"
        ),
        {"thresholds": json.dumps(payload), "id": resolved_id},
    )
    return SuccessResponse(data=body.rules)


@router.delete("/{tenant_id}", status_code=204)
@require_permission(PERMISSIONS.TENANT_DEACTIVATE)
async def delete_tenant(
    tenant_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """Tenants are never hard-deleted (CLAUDE.md §1, §28) — use PATCH /{tenant_id}/deactivate.
    The onboarding wizard used to call this to roll back a failed signup; it now creates
    the tenant and its TA admin atomically in one POST / request, so no caller remains."""
    raise HTTPException(
        status_code=409,
        detail={
            "code": "USE_DEACTIVATE",
            "message": "Tenants are never deleted; use PATCH /{tenant_id}/deactivate.",
        },
    )


async def _log_tenant_activity(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    actor_id: str,
    action: str,
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
    note: Optional[str] = None,
) -> None:
    actor_email_row = (
        await db.execute(
            text("SELECT email FROM users WHERE id = :uid LIMIT 1"),
            {"uid": actor_id},
        )
    ).fetchone()
    actor_email = actor_email_row.email if actor_email_row else None

    await db.execute(
        text(
            "INSERT INTO tenant_activity_log "
            "(tenant_id, actor_id, actor_email, action, old_value, new_value, note) "
            "VALUES (:tid, :aid, :aemail, :action, :old, :new, :note)"
        ),
        {
            "tid": str(tenant_id),
            "aid": actor_id,
            "aemail": actor_email,
            "action": action,
            "old": old_value,
            "new": new_value,
            "note": note,
        },
    )


@router.post(
    "/{tenant_id}/contacts/bulk",
    response_model=SuccessResponse[dict],
    status_code=201,
)
@require_permission(PERMISSIONS.TENANT_CONFIGURE)
async def save_tenant_contacts_bulk(
    tenant_id: uuid.UUID,
    body: TenantContactsBulkIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[dict]:
    """SA-only: save/replace address + structured contacts for a tenant.

    Replaces all existing tenant_contacts rows. The caller must include the
    primary contact in the list (is_primary=True). At most one primary is
    allowed (enforced by unique index).
    """
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})

    tid = str(tenant_id)

    # Verify tenant exists
    if not (
        await db.execute(text("SELECT id FROM tenants WHERE id = :id"), {"id": tid})
    ).fetchone():
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": "Tenant not found"}
        )

    primary_count = sum(1 for c in body.contacts if c.is_primary)
    if body.contacts and primary_count != 1:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_CONTACTS",
                "message": "Exactly one contact must be marked is_primary=true",
            },
        )

    # Update address on tenant
    if body.address:
        await db.execute(
            text(
                "UPDATE tenants SET "
                "address_line1=:a1, address_line2=:a2, city=:city, "
                "state_province=:sp, postal_code=:pc, country=:country "
                "WHERE id=:tid"
            ),
            {
                "a1": body.address.address_line1,
                "a2": body.address.address_line2,
                "city": body.address.city,
                "sp": body.address.state_province,
                "pc": body.address.postal_code,
                "country": body.address.country,
                "tid": tid,
            },
        )

    # Replace contacts (delete then insert for idempotency)
    await db.execute(
        text("DELETE FROM tenant_contacts WHERE tenant_id = :tid"),
        {"tid": tid},
    )

    for contact in body.contacts:
        if not contact.full_name.strip():
            continue
        await db.execute(
            text(
                "INSERT INTO tenant_contacts "
                "(tenant_id, is_primary, full_name, position_title, email, phone, mobile) "
                "VALUES (:tid, :primary, :name, :title, :email, :phone, :mobile)"
            ),
            {
                "tid": tid,
                "primary": contact.is_primary,
                "name": contact.full_name.strip(),
                "title": contact.position_title,
                "email": contact.email,
                "phone": contact.phone,
                "mobile": contact.mobile,
            },
        )

    return SuccessResponse(data={"saved": len(body.contacts)})


@router.get("/{tenant_id}/contacts", response_model=SuccessResponse[List[TenantContactOut]])
@require_permission(PERMISSIONS.TENANT_CONFIGURE, read_only_exempt=True)
async def list_tenant_contacts(
    tenant_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[List[TenantContactOut]]:
    """SA-only: list structured contacts for a tenant."""
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})

    rows = (
        await db.execute(
            text(
                "SELECT id, tenant_id, is_primary, full_name, position_title, "
                "email, phone, mobile, created_at "
                "FROM tenant_contacts WHERE tenant_id = :tid "
                "ORDER BY is_primary DESC, created_at ASC"
            ),
            {"tid": str(tenant_id)},
        )
    ).fetchall()

    return SuccessResponse(
        data=[
            TenantContactOut(
                id=row.id,
                tenant_id=row.tenant_id,
                is_primary=row.is_primary,
                full_name=row.full_name,
                position_title=row.position_title,
                email=row.email,
                phone=row.phone,
                mobile=row.mobile,
                created_at=row.created_at.isoformat(),
            )
            for row in rows
        ]
    )


@router.post(
    "/{tenant_id}/contacts", status_code=201, response_model=SuccessResponse[TenantContactOut]
)
@require_permission(PERMISSIONS.TENANT_MANAGE)
async def create_tenant_contact(
    tenant_id: uuid.UUID,
    body: TenantContactIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TenantContactOut]:
    """SA-only: create a contact for any tenant. Same validation as POST /me/contacts."""
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})
    result = await _create_tenant_contact(db, tenant_id, body)
    try:
        await _log_tenant_activity(
            db,
            tenant_id,
            str(user.user_id),
            action="CONTACT_CREATED",
            new_value=result.full_name,
        )
    except Exception:
        pass
    return SuccessResponse(data=result)


@router.patch(
    "/{tenant_id}/contacts/{contact_id}", response_model=SuccessResponse[TenantContactOut]
)
@require_permission(PERMISSIONS.TENANT_MANAGE)
async def update_tenant_contact(
    tenant_id: uuid.UUID,
    contact_id: uuid.UUID,
    body: TenantContactIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TenantContactOut]:
    """SA-only: update a contact belonging to any tenant. 404 if the contact
    does not belong to tenant_id. Same validation as PATCH /me/contacts/{id}."""
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})
    result = await _update_tenant_contact(db, tenant_id, contact_id, body)
    try:
        await _log_tenant_activity(
            db,
            tenant_id,
            str(user.user_id),
            action="CONTACT_UPDATED",
            new_value=result.full_name,
        )
    except Exception:
        pass
    return SuccessResponse(data=result)


@router.patch("/{tenant_id}/contract", response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.TENANT_CONTRACT_EDIT)
async def update_tenant_contract(
    tenant_id: uuid.UUID,
    body: ContractUpdateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[dict]:
    """SA-only: set or update contract start/end dates with a mandatory audit note.

    Resets contract_expiry_notified so milestone alerts re-fire from the new end date.
    If the tenant was auto-suspended due to contract expiry and the new end date is
    in the future, the tenant is automatically reactivated to ACTIVE.
    """
    from datetime import date as _date

    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})

    note = body.note.strip() if body.note else ""
    if not note:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "NOTE_REQUIRED",
                "message": "A note explaining the contract change is required.",
            },
        )

    row = (
        await db.execute(
            text(
                "SELECT id, name, status, contract_start, contract_end FROM tenants WHERE id = :id"
            ),
            {"id": str(tenant_id)},
        )
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Validate date strings and convert to datetime.date for asyncpg
    def _parse_date(s: Optional[str], field: str) -> Optional[_date]:
        if s is None:
            return None
        try:
            return _date.fromisoformat(s)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "INVALID_DATE",
                    "field": field,
                    "message": f"'{s}' is not a valid ISO date (YYYY-MM-DD).",
                },
            )

    new_start = _parse_date(body.contract_start, "contract_start")
    new_end = _parse_date(body.contract_end, "contract_end")

    old_start = str(row.contract_start) if row.contract_start else None
    old_end = str(row.contract_end) if row.contract_end else None

    # Auto-reactivate if tenant was suspended because of expiry and new end is in the future
    should_reactivate = (
        str(row.status) == "SUSPENDED" and new_end is not None and new_end >= _date.today()
    )

    await db.execute(
        text(
            "UPDATE tenants SET "
            "contract_start = :cs, contract_end = :ce, "
            "contract_expiry_notified = '[]'::jsonb, "
            "updated_at = now() "
            "WHERE id = :id"
        ),
        {"cs": new_start, "ce": new_end, "id": str(tenant_id)},
    )

    if should_reactivate:
        await db.execute(
            text(
                "UPDATE tenants SET status = 'ACTIVE', is_active = true, updated_at = now() WHERE id = :id"
            ),
            {"id": str(tenant_id)},
        )

    try:
        old_summary = f"start={old_start or 'none'} end={old_end or 'none'}"
        new_summary = f"start={new_start or 'none'} end={new_end or 'none'}"
        await _log_tenant_activity(
            db,
            tenant_id,
            str(user.user_id),
            action="CONTRACT_DATES_UPDATED",
            old_value=old_summary,
            new_value=new_summary,
            note=note,
        )
    except Exception:
        pass

    return SuccessResponse(
        data={
            "contract_start": new_start,
            "contract_end": new_end,
            "reactivated": should_reactivate,
        }
    )


@router.patch("/{tenant_id}/suspend", response_model=SuccessResponse[TenantStatusResponse])
@require_permission(PERMISSIONS.TENANT_DEACTIVATE)
async def suspend_tenant(
    tenant_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TenantStatusResponse]:
    """SA-only: temporarily suspend a tenant. All non-SA logins blocked immediately."""
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})
    row = (
        await db.execute(
            text("SELECT id, name, status FROM tenants WHERE id = :id"),
            {"id": str(tenant_id)},
        )
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if row.status == "SUSPENDED":
        raise HTTPException(
            status_code=422,
            detail={"code": "ALREADY_SUSPENDED", "message": "Tenant is already suspended"},
        )
    if row.status == "DEACTIVATED":
        raise HTTPException(
            status_code=422,
            detail={
                "code": "TENANT_DEACTIVATED",
                "message": "Cannot suspend a deactivated tenant. Reactivate first.",
            },
        )
    await db.execute(
        text(
            "UPDATE tenants SET status = 'SUSPENDED', is_active = false, updated_at = now() WHERE id = :id"
        ),
        {"id": str(tenant_id)},
    )
    await revoke_tenant_tokens(str(tenant_id))
    try:
        await _log_tenant_activity(
            db,
            tenant_id,
            str(user.user_id),
            action="SUSPEND",
            old_value=row.status,
            new_value="SUSPENDED",
        )
    except Exception:
        pass  # log write failure must never roll back the status change
    return SuccessResponse(
        data=TenantStatusResponse(id=tenant_id, name=row.name, status="SUSPENDED")
    )


@router.patch("/{tenant_id}/reactivate", response_model=SuccessResponse[TenantStatusResponse])
@require_permission(PERMISSIONS.TENANT_DEACTIVATE)
async def reactivate_tenant(
    tenant_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TenantStatusResponse]:
    """SA-only: restore a suspended or deactivated tenant to ACTIVE."""
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})
    row = (
        await db.execute(
            text("SELECT id, name, status FROM tenants WHERE id = :id"),
            {"id": str(tenant_id)},
        )
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if row.status == "ACTIVE":
        raise HTTPException(
            status_code=422,
            detail={"code": "ALREADY_ACTIVE", "message": "Tenant is already active"},
        )
    await db.execute(
        text(
            "UPDATE tenants SET status = 'ACTIVE', is_active = true, updated_at = now() WHERE id = :id"
        ),
        {"id": str(tenant_id)},
    )
    try:
        await _log_tenant_activity(
            db,
            tenant_id,
            str(user.user_id),
            action="REACTIVATE",
            old_value=row.status,
            new_value="ACTIVE",
        )
    except Exception:
        pass  # log write failure must never roll back the status change
    return SuccessResponse(data=TenantStatusResponse(id=tenant_id, name=row.name, status="ACTIVE"))


@router.patch("/{tenant_id}/deactivate", response_model=SuccessResponse[TenantStatusResponse])
@require_permission(PERMISSIONS.TENANT_DEACTIVATE)
async def deactivate_tenant(
    tenant_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TenantStatusResponse]:
    """SA-only: permanently deactivate a tenant (soft delete). Data preserved."""
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})
    row = (
        await db.execute(
            text("SELECT id, name, status FROM tenants WHERE id = :id"),
            {"id": str(tenant_id)},
        )
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if row.status == "DEACTIVATED":
        raise HTTPException(
            status_code=422,
            detail={"code": "ALREADY_DEACTIVATED", "message": "Tenant is already deactivated"},
        )
    await db.execute(
        text(
            "UPDATE tenants SET status = 'DEACTIVATED', is_active = false, updated_at = now() WHERE id = :id"
        ),
        {"id": str(tenant_id)},
    )
    await revoke_tenant_tokens(str(tenant_id))
    try:
        await _log_tenant_activity(
            db,
            tenant_id,
            str(user.user_id),
            action="DEACTIVATE",
            old_value=row.status,
            new_value="DEACTIVATED",
        )
    except Exception:
        pass  # log write failure must never roll back the status change
    return SuccessResponse(
        data=TenantStatusResponse(id=tenant_id, name=row.name, status="DEACTIVATED")
    )


# ── TA Admin User ────────────────────────────────────────────────────────────


class TaUserOut(BaseModel):
    id: str
    full_name: Optional[str]
    email: str


class TaUserUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None


@router.get("/{tenant_id}/admin-user", response_model=SuccessResponse[TaUserOut])
@require_permission(PERMISSIONS.TENANT_MANAGE, read_only_exempt=True)
async def get_tenant_admin_user(
    tenant_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TaUserOut]:
    """SA-only: return the primary TA user for a tenant."""
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})
    row = (
        await db.execute(
            text(
                "SELECT id, full_name, email FROM users "
                "WHERE tenant_id = :tid AND system_role = 'TA' AND is_active = true "
                "ORDER BY created_at ASC LIMIT 1"
            ),
            {"tid": str(tenant_id)},
        )
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No active TA user found for this tenant")
    return SuccessResponse(data=TaUserOut(id=str(row.id), full_name=row.full_name, email=row.email))


@router.patch("/{tenant_id}/admin-user", response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.TENANT_MANAGE)
async def update_tenant_admin_user(
    tenant_id: uuid.UUID,
    body: TaUserUpdateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[dict]:
    """SA-only: update the TA user's name and/or email."""
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})

    row = (
        await db.execute(
            text(
                "SELECT id, full_name, email FROM users "
                "WHERE tenant_id = :tid AND system_role = 'TA' AND is_active = true "
                "ORDER BY created_at ASC LIMIT 1"
            ),
            {"tid": str(tenant_id)},
        )
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No active TA user found for this tenant")

    set_parts: list[str] = ["updated_at = now()"]
    params: dict = {"uid": str(row.id)}
    changes: dict = {}

    if body.full_name is not None and body.full_name.strip() != (row.full_name or ""):
        set_parts.append("full_name = :full_name")
        params["full_name"] = body.full_name.strip()
        changes["ta_full_name"] = (row.full_name, body.full_name.strip())

    if body.email is not None:
        normalized_email = body.email.strip().lower()
        if normalized_email != row.email.strip().lower():
            # Email is globally unique (uq_users_email_lower) — check across
            # ALL tenants, excluding this user's own row. Never reveal which
            # tenant already owns the email.
            existing = (
                await db.execute(
                    text("SELECT id FROM users WHERE lower(email) = :email AND id != :uid"),
                    {"email": normalized_email, "uid": str(row.id)},
                )
            ).fetchone()
            if existing:
                raise _duplicate_email_http_exception()
            set_parts.append("email = :email")
            params["email"] = normalized_email
            changes["ta_email"] = (row.email, normalized_email)

    if not changes:
        return SuccessResponse(data={"changes": 0, "fields": []})

    try:
        await db.execute(
            text(f"UPDATE users SET {', '.join(set_parts)} WHERE id = :uid"),
            params,
        )
    except IntegrityError as exc:
        if _is_duplicate_email_violation(exc):
            raise _duplicate_email_http_exception() from exc
        raise
    for field, (old_val, new_val) in changes.items():
        try:
            await _log_tenant_activity(
                db,
                tenant_id,
                str(user.user_id),
                action=f"PROFILE_UPDATE_{field.upper()}",
                old_value=old_val,
                new_value=new_val,
            )
        except Exception:
            pass
    return SuccessResponse(data={"changes": len(changes), "fields": list(changes.keys())})


# ── Feature Flags ────────────────────────────────────────────────────────────


class FeatureFlagsUpdateRequest(BaseModel):
    feature_flags: dict  # e.g. {"LOGISTICS": true, "AI_ANALYTICS": false}


@router.patch("/{tenant_id}/feature-flags", response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.TENANT_MANAGE)
async def update_feature_flags(
    tenant_id: uuid.UUID,
    body: FeatureFlagsUpdateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[dict]:
    """Removed (S10): per-tenant feature overrides now go through the add-on
    endpoints (POST /{tenant_id}/addons) so a grant survives a plan change and
    can carry a price. The route and its permission stay registered — only for
    the CI permission-drift check — and always 409s. See CLAUDE.md §15."""
    raise HTTPException(
        status_code=409,
        detail={
            "code": "USE_ADDONS",
            "message": "Direct feature-flag overrides are no longer supported. "
            "Grant a free override or purchased add-on via POST "
            "/{tenant_id}/addons instead.",
        },
    )
