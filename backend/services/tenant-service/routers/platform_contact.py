"""Platform contact details (080) — public read, SA-only edit, audited.

Routes are declared as /public/contact and /platform/contact, included
under the same "/api/v1/tenants" prefix as every other tenant-service
router, so the full paths are /api/v1/tenants/public/contact and
/api/v1/tenants/platform/contact.

GET /public/contact is intentionally unauthenticated (no @require_permission)
and is allowlisted in scripts/ci_drift_check.py next to list_public_packages.
PUT /platform/contact follows the same SA-only + platform_config_log pattern
as the PRICE routes in routers/tenants.py (platform:tier_config_edit).
"""

from __future__ import annotations

import re
from typing import Optional

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_current_user, get_db_session
from shared.cache.rate_limit import client_ip, hit_bucket as rate_limit_hit
from shared.db.session import AsyncSessionLocal
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse

router = APIRouter()

_PHONE_RE = re.compile(r"^[+0-9 ()-]{6,30}$")

_FIELD_LIMITS = {
    "support_email": 255,
    "phone": 30,
    "whatsapp": 30,
    "address_en": None,
    "address_am": None,
    "hours_en": 200,
    "hours_am": 200,
    "note_en": 300,
    "note_am": 300,
}


class LocalizedText(BaseModel):
    en: Optional[str] = None
    am: Optional[str] = None


class ContactOut(BaseModel):
    configured: bool
    support_email: Optional[str] = None
    phone: Optional[str] = None
    whatsapp: Optional[str] = None
    address: LocalizedText
    hours: LocalizedText
    note: LocalizedText
    updated_at: str


def _row_to_out(row) -> ContactOut:
    return ContactOut(
        configured=bool(row.support_email or row.phone),
        support_email=row.support_email,
        phone=row.phone,
        whatsapp=row.whatsapp,
        address=LocalizedText(en=row.address_en, am=row.address_am),
        hours=LocalizedText(en=row.hours_en, am=row.hours_am),
        note=LocalizedText(en=row.note_en, am=row.note_am),
        updated_at=row.updated_at.isoformat(),
    )


_SELECT_CONTACT = (
    "SELECT support_email, phone, whatsapp, address_en, address_am, "
    "       hours_en, hours_am, note_en, note_am, updated_at, updated_by "
    "FROM platform_contact WHERE id = 1"
)


# ── GET /public/contact ───────────────────────────────────────────────────


@router.get("/public/contact", response_model=SuccessResponse[ContactOut])
async def get_public_contact(request: Request) -> SuccessResponse[ContactOut]:
    await rate_limit_hit("packages", client_ip(request))

    async with AsyncSessionLocal() as db:
        row = (await db.execute(text(_SELECT_CONTACT))).fetchone()

    return SuccessResponse(data=_row_to_out(row))


# ── PUT /platform/contact ─────────────────────────────────────────────────


class ContactUpdateRequest(BaseModel):
    support_email: Optional[str] = None
    phone: Optional[str] = None
    whatsapp: Optional[str] = None
    address_en: Optional[str] = None
    address_am: Optional[str] = None
    hours_en: Optional[str] = None
    hours_am: Optional[str] = None
    note_en: Optional[str] = None
    note_am: Optional[str] = None
    reason: str

    @field_validator(
        "support_email",
        "phone",
        "whatsapp",
        "address_en",
        "address_am",
        "hours_en",
        "hours_am",
        "note_en",
        "note_am",
        mode="before",
    )
    @classmethod
    def _blank_to_none(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v


_EDITABLE_CONTACT_FIELDS = tuple(_FIELD_LIMITS.keys())


@router.put("/platform/contact", response_model=SuccessResponse[ContactOut])
@require_permission(PERMISSIONS.PLATFORM_CONTACT_EDIT)
async def update_platform_contact(
    body: ContactUpdateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[ContactOut]:
    """SA-only: update the single platform_contact row.

    Every field is optional and nullable (empty string is coerced to NULL by
    the _blank_to_none validator above). `reason` is required, non-blank, and
    logged once per changed field to platform_config_log (entity_type
    'CONTACT', entity_key 'platform') — unchanged fields are not logged.
    """
    if not user or user.role != "SA":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "SA only"})

    reason = body.reason.strip() if body.reason else ""
    if not reason:
        raise HTTPException(
            status_code=422, detail={"code": "REASON_REQUIRED", "message": "reason is required."}
        )

    if body.support_email is not None:
        try:
            validate_email(body.support_email, check_deliverability=False)
        except EmailNotValidError:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "INVALID_EMAIL",
                    "message": "support_email must be a valid email address.",
                },
            )

    for field in ("phone", "whatsapp"):
        value = getattr(body, field)
        if value is not None and not _PHONE_RE.match(value):
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "INVALID_PHONE",
                    "message": f"{field} must match {_PHONE_RE.pattern}.",
                },
            )

    fields_set = body.model_fields_set - {"reason"}
    for field in fields_set:
        limit = _FIELD_LIMITS.get(field)
        value = getattr(body, field)
        if limit is not None and value is not None and len(value) > limit:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "FIELD_TOO_LONG",
                    "message": f"{field} must be at most {limit} characters.",
                },
            )

    old_row = (await db.execute(text(_SELECT_CONTACT))).fetchone()

    editable = [f for f in _EDITABLE_CONTACT_FIELDS if f in fields_set]
    if editable:
        set_parts = ["updated_at = now()", "updated_by = :uid"]
        params: dict = {"uid": str(user.user_id)}
        for field in editable:
            set_parts.append(f"{field} = :{field}")
            params[field] = getattr(body, field)

        await db.execute(
            text(f"UPDATE platform_contact SET {', '.join(set_parts)} WHERE id = 1"),
            params,
        )

        actor_email = getattr(user, "email", None)
        for field in editable:
            old_val = getattr(old_row, field) if old_row else None
            new_val = getattr(body, field)
            if old_val == new_val:
                continue
            await db.execute(
                text(
                    "INSERT INTO platform_config_log "
                    "  (entity_type, entity_key, field, old_value, new_value, "
                    "   reason, actor_id, actor_email) "
                    "VALUES ('CONTACT', 'platform', :field, :old, :new, :reason, :actor_id, :actor_email)"
                ),
                {
                    "field": field,
                    "old": old_val,
                    "new": new_val,
                    "reason": reason,
                    "actor_id": str(user.user_id),
                    "actor_email": actor_email,
                },
            )

    row = (await db.execute(text(_SELECT_CONTACT))).fetchone()
    return SuccessResponse(data=_row_to_out(row))
