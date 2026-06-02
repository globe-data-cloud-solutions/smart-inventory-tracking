import json
import re
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_current_user, get_db_session
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse
from schemas.tenant import TenantCreateRequest, TenantResponse


def _slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:80]

router = APIRouter()


@router.get("/", response_model=SuccessResponse[List[TenantResponse]])
@require_permission(PERMISSIONS.TENANT_LIST)
async def list_tenants(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[List[TenantResponse]]:
    from sqlalchemy import text
    result = await db.execute(
        text(
            "SELECT id, name, slug, organisation_type, onboarding_complete, default_locale, is_active "
            "FROM tenants WHERE is_active = true ORDER BY created_at DESC"
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
            )
            for row in rows
        ]
    )


@router.post("/", status_code=201, response_model=SuccessResponse[TenantResponse])
@require_permission(PERMISSIONS.TENANT_CREATE)
async def create_tenant(
    body: TenantCreateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TenantResponse]:
    from sqlalchemy import text
    tenant_id = uuid.uuid4()
    base_slug = _slugify(body.name) or str(tenant_id)[:8]
    # Ensure uniqueness: append short UUID suffix on collision
    slug = base_slug
    row = await db.execute(text("SELECT id FROM tenants WHERE slug = :s"), {"s": slug})
    if row.fetchone():
        slug = f"{base_slug}-{str(tenant_id)[:8]}"
    await db.execute(
        text(
            "INSERT INTO tenants (id, name, slug, plan_id, default_locale, organisation_type) "
            "VALUES (:id, :name, :slug, :plan_id, :locale, :org_type)"
        ),
        {
            "id": str(tenant_id),
            "name": body.name,
            "slug": slug,
            "plan_id": str(body.plan_id),
            "locale": body.default_locale,
            "org_type": body.organisation_type,
        },
    )

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
            admin_user_id=admin_user_id,
            admin_email=admin_email_out,
        )
    )


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
        )
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
