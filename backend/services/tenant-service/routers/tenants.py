import json
import re
import uuid
from typing import List, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_current_user, get_db_session
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse
from schemas.tenant import TenantCreateRequest, TenantResponse, VALID_PLAN_TIERS, VALID_LOCALES


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
    plan_tier:      Optional[str]
    default_locale: str = "en"      # persisted user-facing locale preference
    contact_name:   Optional[str]   # legacy single-contact field
    contact_email:  Optional[str]
    contact_phone:  Optional[str]
    contract_start: Optional[str]   # ISO date string "YYYY-MM-DD" or None
    contract_end:   Optional[str]
    notes:          Optional[str]
    sku_cap:        Optional[int]
    address_line1:  Optional[str]
    address_line2:  Optional[str]
    city:           Optional[str]
    state_province: Optional[str]
    postal_code:    Optional[str]
    country:        Optional[str]
    contacts: List[RegistryContact] = []
    user_count: int
    node_count: int
    created_at: str                 # ISO datetime string
    ta_name:  Optional[str] = None  # TA admin user name
    ta_email: Optional[str] = None  # TA admin user email
    ta_user_id: Optional[str] = None  # TA admin user UUID (for edit link)
    industry: Optional[str] = None
    feature_flags: dict = {}


class TenantContactIn(BaseModel):
    is_primary: bool = False
    full_name: str
    position_title: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None


class TenantAddressIn(BaseModel):
    address_line1:  Optional[str] = None
    address_line2:  Optional[str] = None
    city:           Optional[str] = None
    state_province: Optional[str] = None
    postal_code:    Optional[str] = None
    country:        Optional[str] = None


class TenantContactsBulkIn(BaseModel):
    address:  Optional[TenantAddressIn] = None
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

# Hardcoded fallback used when platform_tier_config table is not yet available.
TIER_LIMITS: dict[str, dict[str, int | None]] = {
    "STARTER":    {"max_warehouses": 3,    "max_users": 5},
    "GROWTH":     {"max_warehouses": 10,   "max_users": 25},
    "ENTERPRISE": {"max_warehouses": None, "max_users": None},
}

# Feature flags that are explicitly toggled by plan tier.
# Merged (via JSONB ||) into the tenant's feature_flags on every Plan PATCH.
# Only keys listed here are overwritten; other flags are left unchanged.
PLAN_TIER_FEATURE_DEFAULTS: dict[str, dict[str, bool]] = {
    "STARTER":    {"TRANSFERS_SISTER": False},
    "GROWTH":     {"TRANSFERS_SISTER": True},
    "ENTERPRISE": {"TRANSFERS_SISTER": True},
}

# Mirrors wizard_service.py defaults — used when org_type changes via profile edit.
FEATURE_FLAG_DEFAULTS: dict[str, dict[str, bool]] = {
    "PRODUCER": {"LOGISTICS": False, "AI_ANALYTICS": False, "ADVANCED_BATCH_TRACKING": True,  "FLEET_MANAGEMENT": False},
    "RETAILER": {"LOGISTICS": True,  "AI_ANALYTICS": True,  "ADVANCED_BATCH_TRACKING": False, "FLEET_MANAGEMENT": True},
    "HYBRID":   {"LOGISTICS": True,  "AI_ANALYTICS": True,  "ADVANCED_BATCH_TRACKING": True,  "FLEET_MANAGEMENT": True},
}
APPROVAL_DEFAULTS: dict[str, dict] = {
    "PRODUCER": {"inventory:adjust": {"low": 100,  "medium": 500}},
    "RETAILER": {"inventory:adjust": {"low": 500,  "medium": 5000}},
    "HYBRID":   {"inventory:adjust": {"low": 250,  "medium": 2000}},
}


async def _get_platform_tier_limits(
    db: AsyncSession, tier: str
) -> dict[str, int | None]:
    """Read limits from platform_tier_config; fall back to hardcoded TIER_LIMITS.

    This indirection lets SA override defaults without a code deploy. The fallback
    guarantees the system works before migration 068 runs or on a fresh dev DB.
    """
    try:
        row = (await db.execute(
            text("SELECT max_warehouses, max_users FROM platform_tier_config WHERE tier = :tier"),
            {"tier": tier},
        )).fetchone()
        if row:
            return {"max_warehouses": row.max_warehouses, "max_users": row.max_users}
    except Exception:
        pass  # table may not exist yet — fall through to defaults
    return dict(TIER_LIMITS.get(tier, {"max_warehouses": None, "max_users": None}))


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

    rows = (await db.execute(text("""
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
        ORDER BY t.created_at DESC
    """))).fetchall()

    return SuccessResponse(data=[
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
            contract_end=str(row.contract_end)     if row.contract_end   else None,
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
        )
        for row in rows
    ])


class TierConfigEntry(BaseModel):
    tier: str
    max_warehouses: Optional[int]  # None = unlimited
    max_users: Optional[int]       # None = unlimited


class TierConfigUpdateRequest(BaseModel):
    tiers: List[TierConfigEntry]


@router.get("/platform/tier-config", response_model=SuccessResponse[List[TierConfigEntry]])
@require_permission(PERMISSIONS.PLATFORM_TIER_CONFIG_VIEW)
async def get_platform_tier_config(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[List[TierConfigEntry]]:
    """SA-only: return the current platform tier limits for all three tiers."""
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})
    rows = (await db.execute(
        text("SELECT tier, max_warehouses, max_users FROM platform_tier_config ORDER BY tier"),
    )).fetchall()
    if not rows:
        # Table not yet seeded — return hardcoded defaults
        return SuccessResponse(data=[
            TierConfigEntry(tier=t, **v) for t, v in TIER_LIMITS.items()
        ])
    return SuccessResponse(data=[
        TierConfigEntry(tier=row.tier, max_warehouses=row.max_warehouses, max_users=row.max_users)
        for row in rows
    ])


@router.patch("/platform/tier-config", response_model=SuccessResponse[List[TierConfigEntry]])
@require_permission(PERMISSIONS.PLATFORM_TIER_CONFIG_EDIT)
async def update_platform_tier_config(
    body: TierConfigUpdateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[List[TierConfigEntry]]:
    """SA-only: update platform-level tier defaults.

    Changes apply to the next tenant creation or plan change.
    Existing tenant caps (stored per-tenant) are NOT retroactively changed.
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

    for entry in body.tiers:
        await db.execute(
            text(
                "INSERT INTO platform_tier_config (tier, max_warehouses, max_users, updated_at, updated_by_id) "
                "VALUES (:tier, :max_wh, :max_u, now(), :uid) "
                "ON CONFLICT (tier) DO UPDATE SET "
                "max_warehouses = EXCLUDED.max_warehouses, "
                "max_users      = EXCLUDED.max_users, "
                "updated_at     = now(), "
                "updated_by_id  = EXCLUDED.updated_by_id"
            ),
            {"tier": entry.tier, "max_wh": entry.max_warehouses,
             "max_u": entry.max_users, "uid": str(user.user_id)},
        )

    rows = (await db.execute(
        text("SELECT tier, max_warehouses, max_users FROM platform_tier_config ORDER BY tier"),
    )).fetchall()
    return SuccessResponse(data=[
        TierConfigEntry(tier=row.tier, max_warehouses=row.max_warehouses, max_users=row.max_users)
        for row in rows
    ])


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

    exists = (await db.execute(
        text("SELECT id FROM tenants WHERE id = :tid"),
        {"tid": str(tenant_id)},
    )).fetchone()
    if not exists:
        raise HTTPException(status_code=404, detail="Tenant not found")

    rows = (await db.execute(
        text("""
            SELECT id, tenant_id, actor_id, actor_email,
                   action, old_value, new_value, note, created_at
            FROM tenant_activity_log
            WHERE tenant_id = :tid
            ORDER BY created_at DESC
            LIMIT :lim OFFSET :off
        """),
        {"tid": str(tenant_id), "lim": limit, "off": offset},
    )).fetchall()

    return SuccessResponse(data=[
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
    ])


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
                "code":    "INVALID_ORGANISATION_TYPE",
                "message": f"organisation_type must be one of {sorted(VALID_ORGANISATION_TYPES)}, "
                           f"got '{body.organisation_type}'.",
            },
        )

    if body.plan_tier not in VALID_PLAN_TIERS:
        raise HTTPException(
            status_code=422,
            detail={
                "code":    "INVALID_TIER",
                "message": f"plan_tier must be one of {sorted(VALID_PLAN_TIERS)}, "
                           f"got '{body.plan_tier}'.",
            },
        )

    # Slug resolution: use caller-provided slug (validated) or auto-generate from name.
    if body.slug is not None:
        candidate = body.slug.strip().lower()
        if not _validate_slug(candidate):
            raise HTTPException(
                status_code=422,
                detail={
                    "code":    "INVALID_SLUG",
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
                    "code":    "SLUG_ALREADY_EXISTS",
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
    tier_limits = await _get_platform_tier_limits(db, body.plan_tier)
    # sku_cap is only meaningful for PRODUCER tenants; store NULL for RETAILER/HYBRID.
    effective_sku_cap = body.sku_cap if body.organisation_type == "PRODUCER" else None
    try:
        await db.execute(
            text(
                "INSERT INTO tenants (id, name, slug, plan_id, default_locale, organisation_type, "
                "plan_tier, max_warehouses, max_users, sku_cap, industry) "
                "VALUES (:id, :name, :slug, :plan_id, :locale, :org_type, "
                "CAST(:plan_tier AS plan_tier), :max_wh, :max_u, :sku_cap, :industry)"
            ),
            {
                "id": str(tenant_id),
                "name": body.name,
                "slug": slug,
                "plan_id": str(body.plan_id),
                "locale": body.default_locale,
                "org_type": body.organisation_type,
                "plan_tier": body.plan_tier,
                "max_wh": tier_limits["max_warehouses"],
                "max_u": tier_limits["max_users"],
                "sku_cap": effective_sku_cap,
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

    # Atomic TA admin user creation — same DB transaction as tenant INSERT.
    admin_user_id: Optional[uuid.UUID] = None
    admin_email_out: Optional[str] = None
    if body.admin_email and body.admin_password:
        import bcrypt as _bcrypt
        pw_hash = _bcrypt.hashpw(body.admin_password.encode(), _bcrypt.gensalt()).decode()
        admin_user_id = uuid.uuid4()
        admin_email_out = body.admin_email
        await db.execute(
            text(
                "INSERT INTO users "
                "  (id, tenant_id, email, full_name, password_hash, "
                "   is_active, must_reset_password, system_role) "
                "VALUES (:id, :tid, :email, :name, :hash, true, true, 'TA')"
            ),
            {
                "id":    str(admin_user_id),
                "tid":   str(tenant_id),
                "email": body.admin_email,
                "name":  body.admin_name or body.admin_email,
                "hash":  pw_hash,
            },
        )

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
            admin_user_id=admin_user_id,
            admin_email=admin_email_out,
        )
    )


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
    row = (await db.execute(
        text(
            "SELECT plan_tier, feature_flags, sku_cap, "
            "       max_warehouses, max_users, "
            "       contract_start, contract_end "
            "FROM   tenants WHERE id = :tid"
        ),
        {"tid": str(user.tenant_id)},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return SuccessResponse(data={
        "plan_tier":       str(row.plan_tier) if row.plan_tier else "ENTERPRISE",
        "feature_flags":   dict(row.feature_flags) if row.feature_flags else {},
        "sku_cap":         row.sku_cap,
        "max_warehouses":  row.max_warehouses,
        "max_users":       row.max_users,
        "contract_start":  str(row.contract_start) if row.contract_start else None,
        "contract_end":    str(row.contract_end)   if row.contract_end   else None,
    })


class PlanUpdateRequest(BaseModel):
    plan_tier: str
    max_warehouses: Optional[int] = None   # if None, auto-set from platform_tier_config
    max_users: Optional[int] = None        # if None, auto-set from platform_tier_config
    sku_cap: Optional[int] = None          # None = unlimited; only updated when key present in body


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
            detail={"code": "INVALID_TIER",
                    "message": f"plan_tier must be one of {sorted(valid_tiers)}"},
        )
    old_row = (await db.execute(
        text("SELECT plan_tier FROM tenants WHERE id = :id"),
        {"id": str(tenant_id)},
    )).fetchone()
    old_tier = str(old_row.plan_tier) if old_row and old_row.plan_tier else None

    # Auto-compute limits from platform_tier_config when body doesn't override them.
    # This keeps tenant caps consistent with platform-level tier defaults.
    platform_limits = await _get_platform_tier_limits(db, body.plan_tier)
    resolved_max_wh = body.max_warehouses if body.max_warehouses is not None else platform_limits["max_warehouses"]
    resolved_max_u  = body.max_users      if body.max_users      is not None else platform_limits["max_users"]

    # Merge tier-gated feature flags in the same UPDATE as the plan_tier change
    # so they commit atomically and check_plan always sees a consistent state.
    tier_features = PLAN_TIER_FEATURE_DEFAULTS.get(body.plan_tier, {})
    plan_set = (
        "UPDATE tenants SET plan_tier = CAST(:tier AS plan_tier), "
        "max_warehouses = :max_wh, max_users = :max_u, updated_at = now()"
    )
    plan_params: dict = {
        "tier": body.plan_tier, "max_wh": resolved_max_wh,
        "max_u": resolved_max_u, "id": str(tenant_id),
    }
    if "sku_cap" in body.model_fields_set:
        plan_set += ", sku_cap = :sku_cap"
        plan_params["sku_cap"] = body.sku_cap
    if tier_features:
        plan_set += ", feature_flags = COALESCE(feature_flags, '{}'::jsonb) || CAST(:tier_flags AS jsonb)"
        plan_params["tier_flags"] = json.dumps(tier_features)
    plan_set += " WHERE id = :id"
    await db.execute(text(plan_set), plan_params)

    try:
        await _log_tenant_activity(
            db, tenant_id, str(user.user_id),
            action="PLAN_CHANGE",
            old_value=old_tier,
            new_value=body.plan_tier,
        )
    except Exception:
        pass  # log failure must not roll back the plan change
    return SuccessResponse(data={
        "plan_tier":      body.plan_tier,
        "max_warehouses": resolved_max_wh,
        "max_users":      resolved_max_u,
    })


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


@router.patch("/{tenant_id}/profile", response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.TENANT_PROFILE_EDIT)
async def update_tenant_profile(
    tenant_id: uuid.UUID,
    body: TenantProfileUpdateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[dict]:
    """SA-only: re-edit wizard-configurable tenant profile fields with full audit trail.

    When organisation_type changes, feature_flags and approval_thresholds are reset
    to the new type's defaults (same as the onboarding wizard does).
    When plan_tier changes, max_warehouses/max_users are recomputed from
    platform_tier_config (same as update_tenant_plan does).
    """
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})

    row = (await db.execute(
        text(
            "SELECT id, name, organisation_type, default_locale, plan_tier, "
            "notes, industry, address_line1, address_line2, city, state_province, postal_code, country "
            "FROM tenants WHERE id = :id"
        ),
        {"id": str(tenant_id)},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Validate supplied values before touching the DB
    if body.organisation_type is not None and body.organisation_type not in VALID_ORGANISATION_TYPES:
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
    old_name     = row.name
    old_org_type = str(row.organisation_type) if row.organisation_type else None
    old_locale   = row.default_locale or "en"
    old_tier     = str(row.plan_tier) if row.plan_tier else None

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
    _ADDR_FIELDS = ("address_line1", "address_line2", "city", "state_province", "postal_code", "country")
    addr_provided = any(f in body.model_fields_set for f in _ADDR_FIELDS)
    addr_changed = addr_provided and any(
        getattr(body, f) != getattr(row, f) for f in _ADDR_FIELDS
    )
    if addr_changed:
        changes["address"] = (
            f"{row.address_line1 or ''}, {row.city or ''}, {row.country or ''}".strip(", "),
            f"{body.address_line1 or ''}, {body.city or ''}, {body.country or ''}".strip(", "),
        )

    if not changes:
        return SuccessResponse(data={"changes": 0, "fields": []})

    # Build SET clause dynamically from actual changes.
    set_parts: list[str] = ["updated_at = now()"]
    params: dict = {"id": str(tenant_id)}

    if "name" in changes:
        set_parts.append("name = :name")
        params["name"] = changes["name"][1]

    if "organisation_type" in changes:
        new_org = changes["organisation_type"][1]
        set_parts.append("organisation_type = CAST(:org_type AS organisation_type)")
        params["org_type"] = new_org
        # Reset feature flags and approval thresholds to match the new org type.
        set_parts.append("feature_flags = CAST(:flags AS jsonb)")
        set_parts.append("approval_thresholds = CAST(:thresholds AS jsonb)")
        params["flags"]      = json.dumps(FEATURE_FLAG_DEFAULTS.get(new_org, {}))
        params["thresholds"] = json.dumps(APPROVAL_DEFAULTS.get(new_org, {}))

    if "default_locale" in changes:
        set_parts.append("default_locale = :locale")
        params["locale"] = changes["default_locale"][1]

    if "plan_tier" in changes:
        new_tier = changes["plan_tier"][1]
        set_parts.append("plan_tier = CAST(:plan_tier AS plan_tier)")
        params["plan_tier"] = new_tier
        platform_limits = await _get_platform_tier_limits(db, new_tier)
        set_parts.append("max_warehouses = :max_wh")
        set_parts.append("max_users = :max_u")
        params["max_wh"] = platform_limits["max_warehouses"]
        params["max_u"]  = platform_limits["max_users"]

    if "notes" in changes:
        set_parts.append("notes = :notes")
        params["notes"] = changes["notes"][1]

    if "industry" in changes:
        set_parts.append("industry = :industry")
        params["industry"] = changes["industry"][1]

    if "address" in changes:
        for f in _ADDR_FIELDS:
            set_parts.append(f"{f} = :{f}")
            params[f] = getattr(body, f)

    await db.execute(
        text(f"UPDATE tenants SET {', '.join(set_parts)} WHERE id = :id"),
        params,
    )

    # Log each changed field as its own activity row so the audit trail is granular.
    for field, (old_val, new_val) in changes.items():
        try:
            await _log_tenant_activity(
                db, tenant_id, str(user.user_id),
                action=f"PROFILE_UPDATE_{field.upper()}",
                old_value=old_val,
                new_value=new_val,
            )
        except Exception:
            pass  # log failure must not roll back the update

    return SuccessResponse(data={"changes": len(changes), "fields": list(changes.keys())})


@router.get("/{tenant_id}", response_model=SuccessResponse[TenantResponse])
@require_permission(PERMISSIONS.TENANT_VIEW)
async def get_tenant(
    tenant_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TenantResponse]:
    from fastapi import HTTPException
    from sqlalchemy import text
    # Accept both UUID (id) and slug lookups
    try:
        uuid.UUID(tenant_id)
        result = await db.execute(
            text("SELECT * FROM tenants WHERE id = :id"), {"id": tenant_id}
        )
    except ValueError:
        result = await db.execute(
            text("SELECT * FROM tenants WHERE slug = :slug"), {"slug": tenant_id}
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
            contract_start=str(row.contract_start) if getattr(row, "contract_start", None) else None,
            contract_end=str(row.contract_end)   if getattr(row, "contract_end",   None) else None,
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

    row = (await db.execute(
        text("SELECT logo_url, banner_url FROM tenants WHERE id = :id"), {"id": resolved_id}
    )).fetchone()
    return SuccessResponse(data={
        "logo_url": row.logo_url if row else None,
        "banner_url": row.banner_url if row else None,
    })


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
        row = await db.execute(text("SELECT id FROM tenants WHERE slug = :slug"), {"slug": tenant_id})
    r = row.fetchone()
    return str(r.id) if r else None


@router.get("/{tenant_id}/approval-rules", response_model=SuccessResponse[List[ApprovalRuleItem]])
@require_permission(PERMISSIONS.TENANT_VIEW)
async def get_approval_rules(
    tenant_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[List[ApprovalRuleItem]]:
    from sqlalchemy import text
    try:
        uuid.UUID(tenant_id)
        result = await db.execute(
            text("SELECT approval_thresholds FROM tenants WHERE id = :id"), {"id": tenant_id}
        )
    except ValueError:
        result = await db.execute(
            text("SELECT approval_thresholds FROM tenants WHERE slug = :slug"), {"slug": tenant_id}
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
    resolved_id = await _resolve_tenant_id(tenant_id, db)
    if not resolved_id:
        raise HTTPException(status_code=404, detail="Tenant not found")
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
    from sqlalchemy import text
    result = await db.execute(
        text("SELECT id FROM tenants WHERE id = :id"), {"id": str(tenant_id)}
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Tenant not found")
    await db.execute(
        text("DELETE FROM tenants WHERE id = :id"), {"id": str(tenant_id)}
    )
    return Response(status_code=204)


async def _log_tenant_activity(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    actor_id: str,
    action: str,
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
    note: Optional[str] = None,
) -> None:
    actor_email_row = (await db.execute(
        text("SELECT email FROM users WHERE id = :uid LIMIT 1"),
        {"uid": actor_id},
    )).fetchone()
    actor_email = actor_email_row.email if actor_email_row else None

    await db.execute(
        text(
            "INSERT INTO tenant_activity_log "
            "(tenant_id, actor_id, actor_email, action, old_value, new_value, note) "
            "VALUES (:tid, :aid, :aemail, :action, :old, :new, :note)"
        ),
        {
            "tid":    str(tenant_id),
            "aid":    actor_id,
            "aemail": actor_email,
            "action": action,
            "old":    old_value,
            "new":    new_value,
            "note":   note,
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
    if not (await db.execute(text("SELECT id FROM tenants WHERE id = :id"), {"id": tid})).fetchone():
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Tenant not found"})

    primary_count = sum(1 for c in body.contacts if c.is_primary)
    if body.contacts and primary_count != 1:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_CONTACTS", "message": "Exactly one contact must be marked is_primary=true"},
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
                "a1":      body.address.address_line1,
                "a2":      body.address.address_line2,
                "city":    body.address.city,
                "sp":      body.address.state_province,
                "pc":      body.address.postal_code,
                "country": body.address.country,
                "tid":     tid,
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
                "tid":     tid,
                "primary": contact.is_primary,
                "name":    contact.full_name.strip(),
                "title":   contact.position_title,
                "email":   contact.email,
                "phone":   contact.phone,
                "mobile":  contact.mobile,
            },
        )

    return SuccessResponse(data={"saved": len(body.contacts)})


@router.get("/{tenant_id}/contacts", response_model=SuccessResponse[List[TenantContactOut]])
@require_permission(PERMISSIONS.TENANT_CONFIGURE)
async def list_tenant_contacts(
    tenant_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[List[TenantContactOut]]:
    """SA-only: list structured contacts for a tenant."""
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})

    rows = (await db.execute(
        text(
            "SELECT id, tenant_id, is_primary, full_name, position_title, "
            "email, phone, mobile, created_at "
            "FROM tenant_contacts WHERE tenant_id = :tid "
            "ORDER BY is_primary DESC, created_at ASC"
        ),
        {"tid": str(tenant_id)},
    )).fetchall()

    return SuccessResponse(data=[
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
    ])


class ContractUpdateRequest(BaseModel):
    contract_start: Optional[str] = None   # "YYYY-MM-DD" or null to clear
    contract_end:   Optional[str] = None   # "YYYY-MM-DD" or null to clear
    note: str                              # required — mandatory audit reason


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
            detail={"code": "NOTE_REQUIRED", "message": "A note explaining the contract change is required."},
        )

    row = (await db.execute(
        text("SELECT id, name, status, contract_start, contract_end FROM tenants WHERE id = :id"),
        {"id": str(tenant_id)},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Validate date strings and convert to datetime.date for asyncpg
    def _parse_date(s: Optional[str]) -> Optional[_date]:
        if s is None:
            return None
        try:
            return _date.fromisoformat(s)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail={"code": "INVALID_DATE", "message": f"'{s}' is not a valid ISO date (YYYY-MM-DD)."},
            )

    new_start = _parse_date(body.contract_start)
    new_end   = _parse_date(body.contract_end)

    old_start = str(row.contract_start) if row.contract_start else None
    old_end   = str(row.contract_end)   if row.contract_end   else None

    # Auto-reactivate if tenant was suspended because of expiry and new end is in the future
    should_reactivate = (
        str(row.status) == "SUSPENDED"
        and new_end is not None
        and new_end >= _date.today()
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
            text("UPDATE tenants SET status = 'ACTIVE', is_active = true, updated_at = now() WHERE id = :id"),
            {"id": str(tenant_id)},
        )

    try:
        old_summary = f"start={old_start or 'none'} end={old_end or 'none'}"
        new_summary = f"start={new_start or 'none'} end={new_end or 'none'}"
        await _log_tenant_activity(
            db, tenant_id, str(user.user_id),
            action="CONTRACT_DATES_UPDATED",
            old_value=old_summary,
            new_value=new_summary,
            note=note,
        )
    except Exception:
        pass

    return SuccessResponse(data={
        "contract_start":  new_start,
        "contract_end":    new_end,
        "reactivated":     should_reactivate,
    })


@router.patch("/{tenant_id}/suspend", response_model=SuccessResponse[TenantStatusResponse])
async def suspend_tenant(
    tenant_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TenantStatusResponse]:
    """SA-only: temporarily suspend a tenant. All non-SA logins blocked immediately."""
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})
    row = (await db.execute(
        text("SELECT id, name, status FROM tenants WHERE id = :id"),
        {"id": str(tenant_id)},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if row.status == "SUSPENDED":
        raise HTTPException(status_code=422, detail={"code": "ALREADY_SUSPENDED", "message": "Tenant is already suspended"})
    if row.status == "DEACTIVATED":
        raise HTTPException(status_code=422, detail={"code": "TENANT_DEACTIVATED", "message": "Cannot suspend a deactivated tenant. Reactivate first."})
    await db.execute(
        text("UPDATE tenants SET status = 'SUSPENDED', is_active = false, updated_at = now() WHERE id = :id"),
        {"id": str(tenant_id)},
    )
    try:
        await _log_tenant_activity(
            db, tenant_id, str(user.user_id),
            action="SUSPEND", old_value=row.status, new_value="SUSPENDED",
        )
    except Exception:
        pass  # log write failure must never roll back the status change
    return SuccessResponse(data=TenantStatusResponse(id=tenant_id, name=row.name, status="SUSPENDED"))


@router.patch("/{tenant_id}/reactivate", response_model=SuccessResponse[TenantStatusResponse])
async def reactivate_tenant(
    tenant_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TenantStatusResponse]:
    """SA-only: restore a suspended or deactivated tenant to ACTIVE."""
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})
    row = (await db.execute(
        text("SELECT id, name, status FROM tenants WHERE id = :id"),
        {"id": str(tenant_id)},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if row.status == "ACTIVE":
        raise HTTPException(status_code=422, detail={"code": "ALREADY_ACTIVE", "message": "Tenant is already active"})
    await db.execute(
        text("UPDATE tenants SET status = 'ACTIVE', is_active = true, updated_at = now() WHERE id = :id"),
        {"id": str(tenant_id)},
    )
    try:
        await _log_tenant_activity(
            db, tenant_id, str(user.user_id),
            action="REACTIVATE", old_value=row.status, new_value="ACTIVE",
        )
    except Exception:
        pass  # log write failure must never roll back the status change
    return SuccessResponse(data=TenantStatusResponse(id=tenant_id, name=row.name, status="ACTIVE"))


@router.patch("/{tenant_id}/deactivate", response_model=SuccessResponse[TenantStatusResponse])
async def deactivate_tenant(
    tenant_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TenantStatusResponse]:
    """SA-only: permanently deactivate a tenant (soft delete). Data preserved."""
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})
    row = (await db.execute(
        text("SELECT id, name, status FROM tenants WHERE id = :id"),
        {"id": str(tenant_id)},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if row.status == "DEACTIVATED":
        raise HTTPException(status_code=422, detail={"code": "ALREADY_DEACTIVATED", "message": "Tenant is already deactivated"})
    await db.execute(
        text("UPDATE tenants SET status = 'DEACTIVATED', is_active = false, updated_at = now() WHERE id = :id"),
        {"id": str(tenant_id)},
    )
    try:
        await _log_tenant_activity(
            db, tenant_id, str(user.user_id),
            action="DEACTIVATE", old_value=row.status, new_value="DEACTIVATED",
        )
    except Exception:
        pass  # log write failure must never roll back the status change
    return SuccessResponse(data=TenantStatusResponse(id=tenant_id, name=row.name, status="DEACTIVATED"))


# ── TA Admin User ────────────────────────────────────────────────────────────

class TaUserOut(BaseModel):
    id: str
    full_name: Optional[str]
    email: str


class TaUserUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None


@router.get("/{tenant_id}/admin-user", response_model=SuccessResponse[TaUserOut])
@require_permission(PERMISSIONS.TENANT_MANAGE)
async def get_tenant_admin_user(
    tenant_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TaUserOut]:
    """SA-only: return the primary TA user for a tenant."""
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})
    row = (await db.execute(
        text(
            "SELECT id, full_name, email FROM users "
            "WHERE tenant_id = :tid AND system_role = 'TA' AND is_active = true "
            "ORDER BY created_at ASC LIMIT 1"
        ),
        {"tid": str(tenant_id)},
    )).fetchone()
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

    row = (await db.execute(
        text(
            "SELECT id, full_name, email FROM users "
            "WHERE tenant_id = :tid AND system_role = 'TA' AND is_active = true "
            "ORDER BY created_at ASC LIMIT 1"
        ),
        {"tid": str(tenant_id)},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No active TA user found for this tenant")

    set_parts: list[str] = ["updated_at = now()"]
    params: dict = {"uid": str(row.id)}
    changes: dict = {}

    if body.full_name is not None and body.full_name.strip() != (row.full_name or ""):
        set_parts.append("full_name = :full_name")
        params["full_name"] = body.full_name.strip()
        changes["ta_full_name"] = (row.full_name, body.full_name.strip())

    if body.email is not None and body.email.lower() != row.email.lower():
        # Check uniqueness across all tenants
        existing = (await db.execute(
            text("SELECT id FROM users WHERE email = :email AND id != :uid"),
            {"email": body.email.lower(), "uid": str(row.id)},
        )).fetchone()
        if existing:
            raise HTTPException(
                status_code=409,
                detail={"code": "EMAIL_CONFLICT", "message": "Email already in use by another account"},
            )
        set_parts.append("email = :email")
        params["email"] = body.email.lower()
        changes["ta_email"] = (row.email, body.email.lower())

    if not changes:
        return SuccessResponse(data={"changes": 0, "fields": []})

    await db.execute(
        text(f"UPDATE users SET {', '.join(set_parts)} WHERE id = :uid"),
        params,
    )
    for field, (old_val, new_val) in changes.items():
        try:
            await _log_tenant_activity(
                db, tenant_id, str(user.user_id),
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
    """SA-only: update individual feature flag toggles without resetting all flags."""
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})

    row = (await db.execute(
        text("SELECT id, name, COALESCE(feature_flags, '{}'::jsonb) AS feature_flags FROM tenants WHERE id = :id"),
        {"id": str(tenant_id)},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found")

    current_flags: dict = dict(row.feature_flags) if row.feature_flags else {}
    # Merge: only update keys supplied in body; unknown keys are silently ignored
    KNOWN_FLAGS = {"LOGISTICS", "AI_ANALYTICS", "ADVANCED_BATCH_TRACKING", "FLEET_MANAGEMENT"}
    merged = dict(current_flags)
    changes: dict = {}
    for flag, val in body.feature_flags.items():
        flag_upper = flag.upper()
        if flag_upper not in KNOWN_FLAGS:
            continue
        if not isinstance(val, bool):
            continue
        if merged.get(flag_upper) != val:
            changes[flag_upper] = (merged.get(flag_upper), val)
            merged[flag_upper] = val

    if not changes:
        return SuccessResponse(data={"changes": 0, "feature_flags": current_flags})

    await db.execute(
        text("UPDATE tenants SET feature_flags = CAST(:flags AS jsonb), updated_at = now() WHERE id = :id"),
        {"flags": json.dumps(merged), "id": str(tenant_id)},
    )
    try:
        await _log_tenant_activity(
            db, tenant_id, str(user.user_id),
            action="FEATURE_FLAGS_UPDATE",
            old_value=json.dumps({k: v[0] for k, v in changes.items()}),
            new_value=json.dumps({k: v[1] for k, v in changes.items()}),
        )
    except Exception:
        pass


# ── TA Self-Service Endpoints ────────────────────────────────────────────────

@router.get("/me/profile", response_model=SuccessResponse[TenantResponse])
@require_permission(PERMISSIONS.TENANT_VIEW)
async def get_my_profile(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TenantResponse]:
    """TA: get their own tenant profile. SA can use /{tenant_id} instead."""
    if not user or not user.tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context")

    row = (await db.execute(
        text(
            "SELECT id, name, slug, organisation_type, onboarding_complete, "
            "default_locale, is_active, status, logo_url, banner_url, "
            "plan_tier, max_warehouses, max_users, "
            "contract_start, contract_end, admin_user_id, admin_email "
            "FROM tenants WHERE id = :id"
        ),
        {"id": str(user.tenant_id)},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found")

    return SuccessResponse(data=TenantResponse(
        id=row.id,
        name=row.name,
        slug=row.slug,
        organisation_type=row.organisation_type,
        onboarding_complete=row.onboarding_complete,
        default_locale=row.default_locale,
        is_active=row.is_active,
        status=row.status,
        logo_url=row.logo_url,
        banner_url=row.banner_url,
        plan_tier=row.plan_tier,
        max_warehouses=row.max_warehouses,
        max_users=row.max_users,
        contract_start=str(row.contract_start) if row.contract_start else None,
        contract_end=str(row.contract_end) if row.contract_end else None,
        admin_user_id=row.admin_user_id,
        admin_email=row.admin_email,
    ))


class TAProfileUpdateRequest(BaseModel):
    """TA can only update specific fields of their own profile."""
    default_locale: Optional[str] = None


@router.patch("/me/profile", response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.TENANT_CONFIGURE)
async def update_my_profile(
    body: TAProfileUpdateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[dict]:
    """TA: update limited fields of their own tenant profile (locale only)."""
    if not user or not user.tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context")

    if body.default_locale is not None and body.default_locale not in VALID_LOCALES:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_LOCALE",
                "message": f"default_locale must be one of {sorted(VALID_LOCALES)}",
            },
        )

    if body.default_locale is None:
        return SuccessResponse(data={"changes": 0})

    old_locale = (await db.execute(
        text("SELECT default_locale FROM tenants WHERE id = :id"),
        {"id": str(user.tenant_id)},
    )).scalar() or "en"

    if body.default_locale == old_locale:
        return SuccessResponse(data={"changes": 0})

    await db.execute(
        text("UPDATE tenants SET default_locale = :locale, updated_at = now() WHERE id = :id"),
        {"locale": body.default_locale, "id": str(user.tenant_id)},
    )

    try:
        await _log_tenant_activity(
            db, user.tenant_id, str(user.user_id),
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
            detail={"code": "NOTE_REQUIRED", "message": "A note explaining the contract change is required."},
        )

    row = (await db.execute(
        text("SELECT id, status, contract_start, contract_end FROM tenants WHERE id = :id"),
        {"id": str(user.tenant_id)},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found")

    def _parse_date(s: Optional[str]) -> Optional[_date]:
        if s is None:
            return None
        try:
            return _date.fromisoformat(s)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail={"code": "INVALID_DATE", "message": f"'{s}' is not a valid ISO date (YYYY-MM-DD)."},
            )

    new_start = _parse_date(body.contract_start)
    new_end   = _parse_date(body.contract_end)

    old_start = str(row.contract_start) if row.contract_start else None
    old_end   = str(row.contract_end) if row.contract_end else None

    # Auto-reactivate if tenant was suspended and new end is in future
    should_reactivate = (
        str(row.status) == "SUSPENDED"
        and new_end is not None
        and new_end >= _date.today()
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
        set_parts.append("contract_expiry_notified = '{}'::jsonb")
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
            db, user.tenant_id, str(user.user_id),
            action="CONTRACT_RENEWAL",
            old_value=f"start:{old_start}, end:{old_end}",
            new_value=f"start:{body.contract_start}, end:{body.contract_end}",
            note=note,
        )
    except Exception:
        pass

    return SuccessResponse(data={
        "contract_start": body.contract_start,
        "contract_end": body.contract_end,
        "reactivated": should_reactivate,
    })


@router.get("/me/contacts", response_model=SuccessResponse[List[TenantContactOut]])
@require_permission(PERMISSIONS.TENANT_VIEW)
async def get_my_contacts(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[List[TenantContactOut]]:
    """TA: get their own tenant's contacts."""
    if not user or not user.tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context")

    rows = (await db.execute(
        text(
            "SELECT id, tenant_id, is_primary, full_name, position_title, "
            "email, phone, mobile, created_at "
            "FROM tenant_contacts WHERE tenant_id = :tid "
            "ORDER BY is_primary DESC, created_at ASC"
        ),
        {"tid": str(user.tenant_id)},
    )).fetchall()

    return SuccessResponse(data=[
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
    ])


@router.post("/me/contacts", status_code=201, response_model=SuccessResponse[TenantContactOut])
@require_permission(PERMISSIONS.TENANT_CONFIGURE)
async def create_my_contact(
    body: TenantContactIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TenantContactOut]:
    """TA: create a contact for their own tenant."""
    from datetime import datetime

    if not user or not user.tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context")

    if not body.full_name or not body.full_name.strip():
        raise HTTPException(status_code=422, detail="full_name is required")

    contact_id = uuid.uuid4()
    now = datetime.utcnow().isoformat()

    await db.execute(
        text(
            "INSERT INTO tenant_contacts "
            "(id, tenant_id, is_primary, full_name, position_title, email, phone, mobile, created_at) "
            "VALUES (:id, :tid, :primary, :name, :title, :email, :phone, :mobile, :now)"
        ),
        {
            "id": contact_id,
            "tid": str(user.tenant_id),
            "primary": body.is_primary,
            "name": body.full_name.strip(),
            "title": body.position_title,
            "email": body.email,
            "phone": body.phone,
            "mobile": body.mobile,
            "now": now,
        },
    )
    await db.commit()

    return SuccessResponse(data=TenantContactOut(
        id=contact_id,
        tenant_id=user.tenant_id,
        is_primary=body.is_primary,
        full_name=body.full_name.strip(),
        position_title=body.position_title,
        email=body.email,
        phone=body.phone,
        mobile=body.mobile,
        created_at=now,
    ))


@router.patch("/me/contacts/{contact_id}", response_model=SuccessResponse[TenantContactOut])
@require_permission(PERMISSIONS.TENANT_CONFIGURE)
async def update_my_contact(
    contact_id: uuid.UUID,
    body: TenantContactIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TenantContactOut]:
    """TA: update a contact in their own tenant."""
    if not user or not user.tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context")

    if not body.full_name or not body.full_name.strip():
        raise HTTPException(status_code=422, detail="full_name is required")

    row = (await db.execute(
        text(
            "SELECT id, tenant_id, is_primary, full_name, position_title, "
            "email, phone, mobile, created_at "
            "FROM tenant_contacts WHERE id = :id AND tenant_id = :tid"
        ),
        {"id": contact_id, "tid": str(user.tenant_id)},
    )).fetchone()
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
            "tid": str(user.tenant_id),
            "primary": body.is_primary,
            "name": body.full_name.strip(),
            "title": body.position_title,
            "email": body.email,
            "phone": body.phone,
            "mobile": body.mobile,
        },
    )
    await db.commit()

    return SuccessResponse(data=TenantContactOut(
        id=contact_id,
        tenant_id=user.tenant_id,
        is_primary=body.is_primary,
        full_name=body.full_name.strip(),
        position_title=body.position_title,
        email=body.email,
        phone=body.phone,
        mobile=body.mobile,
        created_at=row.created_at.isoformat(),
    ))


@router.delete("/me/contacts/{contact_id}", status_code=204)
@require_permission(PERMISSIONS.TENANT_CONFIGURE)
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
    return SuccessResponse(data={"changes": len(changes), "feature_flags": merged})
