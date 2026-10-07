"""Billing (S5) — SA invoice/payment management, TA read-only on its own
tenant, and the public STUB provider webhook.

Fixed paths (/me/..., /public/...) are declared before any parameterised
path (/{tenant_id}/...), per CLAUDE.md §29 route-ordering rule. Included in
main.py AFTER tenants.router (S10): tenants.router owns the fixed
/platform/addons[...] paths, which would otherwise be shadowed by this
router's parameterised /{tenant_id}/addons — Starlette matches routes in
registration order across the whole app, not just within one router.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_current_user, get_db_session, get_db_session_for_tenant
from routers.tenants import _log_tenant_activity
from shared.billing.addons import cancel_addon
from shared.billing.payments import cancel_invoice, create_invoice, mark_failed, mark_paid
from shared.billing.proration import apply_addon_grant_with_proration
from shared.billing.providers import get_provider
from shared.cache.rate_limit import client_ip, hit as rate_limit_hit
from shared.db.rls import set_rls_context
from shared.db.session import AsyncSessionLocal
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse

router = APIRouter()

# Fixed actor recorded for writes the public STUB webhook makes — there is no
# authenticated human behind it. Not a real users row (no FK to enforce it).
SYSTEM_ACTOR_ID = "00000000-0000-0000-0000-000000000099"


def _dt(value: date | datetime | None) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat()


# ── Pydantic models ───────────────────────────────────────────────────────────

class PaymentLineItemOut(BaseModel):
    item_type: str
    item_key: str
    description: Optional[str]
    quantity: int
    unit_amount: Decimal
    amount: Decimal


class PaymentOut(BaseModel):
    id: str
    status: str
    currency: str
    subtotal: Decimal
    vat_rate: Decimal
    vat_amount: Decimal
    total: Decimal
    period_start: str
    period_end: str
    provider: str
    provider_reference: Optional[str]
    paid_at: Optional[str]
    created_at: str
    line_items: list[PaymentLineItemOut]


class SubscriptionOut(BaseModel):
    id: Optional[str]
    tier: Optional[str]
    billing_period: Optional[str]
    status: Optional[str]
    provider: Optional[str]
    amount: Optional[Decimal]
    currency: Optional[str]
    current_period_start: Optional[str]
    current_period_end: Optional[str]
    payments: list[PaymentOut]


class MarkPaidRequest(BaseModel):
    provider_reference: Optional[str] = None
    paid_at: Optional[str] = None
    note: Optional[str] = None


class CancelInvoiceRequest(BaseModel):
    note: str


class InvoiceCreateRequest(BaseModel):
    note: Optional[str] = None


class CheckoutOut(BaseModel):
    payment_id: str
    checkout: dict


class TenantAddonOut(BaseModel):
    id: str
    addon_code: str
    display_name: str
    source: str
    status: str
    amount: Decimal
    currency: str = "ETB"
    starts_on: str
    ends_on: Optional[str]
    note: Optional[str]
    created_at: str
    cancelled_at: Optional[str]


class AddonGrantRequest(BaseModel):
    addon_code: str
    source: str                      # 'OVERRIDE' | 'PURCHASED'
    starts_on: Optional[str] = None  # default today
    ends_on: Optional[str] = None
    note: Optional[str] = None       # required when source=OVERRIDE


class AddonCancelRequest(BaseModel):
    note: str


# ── Shared helpers ────────────────────────────────────────────────────────────

async def _load_subscription_view(db: AsyncSession, tenant_id: str) -> SubscriptionOut:
    sub = (await db.execute(
        text(
            "SELECT id, tier, billing_period, status, provider, amount, currency, "
            "       current_period_start, current_period_end "
            "FROM subscriptions WHERE tenant_id = :tid "
            "ORDER BY (status IN ('ACTIVE', 'PENDING_PAYMENT', 'PAST_DUE')) DESC, "
            "         created_at DESC LIMIT 1"
        ),
        {"tid": str(tenant_id)},
    )).fetchone()

    if sub is None:
        return SubscriptionOut(
            id=None, tier=None, billing_period=None, status=None, provider=None,
            amount=None, currency=None, current_period_start=None, current_period_end=None,
            payments=[],
        )

    payment_rows = (await db.execute(
        text(
            "SELECT id, status, currency, subtotal, vat_rate, vat_amount, total, "
            "       period_start, period_end, provider, provider_reference, paid_at, created_at "
            "FROM payments WHERE subscription_id = :sid ORDER BY created_at DESC"
        ),
        {"sid": str(sub.id)},
    )).fetchall()

    payments: list[PaymentOut] = []
    for p in payment_rows:
        line_item_rows = (await db.execute(
            text(
                "SELECT item_type, item_key, description, quantity, unit_amount, amount "
                "FROM payment_line_items WHERE payment_id = :pid ORDER BY created_at"
            ),
            {"pid": str(p.id)},
        )).fetchall()
        payments.append(PaymentOut(
            id=str(p.id), status=p.status, currency=p.currency,
            subtotal=p.subtotal, vat_rate=p.vat_rate, vat_amount=p.vat_amount, total=p.total,
            period_start=_dt(p.period_start), period_end=_dt(p.period_end),
            provider=p.provider, provider_reference=p.provider_reference,
            paid_at=_dt(p.paid_at), created_at=_dt(p.created_at),
            line_items=[
                PaymentLineItemOut(
                    item_type=li.item_type, item_key=li.item_key, description=li.description,
                    quantity=li.quantity, unit_amount=li.unit_amount, amount=li.amount,
                )
                for li in line_item_rows
            ],
        ))

    return SubscriptionOut(
        id=str(sub.id), tier=sub.tier, billing_period=sub.billing_period, status=sub.status,
        provider=sub.provider, amount=sub.amount, currency=sub.currency,
        current_period_start=_dt(sub.current_period_start), current_period_end=_dt(sub.current_period_end),
        payments=payments,
    )


async def _get_payment_for_tenant(db: AsyncSession, payment_id: str, tenant_id: str):
    row = (await db.execute(
        text("SELECT id, tenant_id, provider, status FROM payments WHERE id = :pid"),
        {"pid": str(payment_id)},
    )).fetchone()
    if row is None or str(row.tenant_id) != str(tenant_id):
        raise HTTPException(status_code=404, detail={"code": "PAYMENT_NOT_FOUND", "message": "Payment not found"})
    return row


def _map_value_error(exc: ValueError) -> HTTPException:
    code = str(exc)
    status_map = {
        "NO_LIVE_SUBSCRIPTION": 409,
        "INVOICE_ALREADY_PENDING": 409,
        "INVALID_PAYMENT_STATE": 422,
        "PAYMENT_NOT_FOUND": 404,
        "PRICE_NOT_AVAILABLE": 422,
        "INVALID_SOURCE": 422,
        "ADDON_NOT_FOUND": 404,
        "ADDON_INACTIVE": 422,
        "FEATURE_ALREADY_IN_PACKAGE": 422,
        "ADDON_ALREADY_ACTIVE": 409,
        "NOTE_REQUIRED": 422,
        "ADDON_PRICE_NOT_AVAILABLE": 422,
        "ADDON_GRANT_NOT_FOUND": 404,
        "ADDON_NOT_ACTIVE": 422,
        "INVOICE_PENDING_SETTLE_FIRST": 409,
    }
    return HTTPException(status_code=status_map.get(code, 422), detail={"code": code, "message": code})


async def _load_tenant_addons(db: AsyncSession, tenant_id: str) -> list[TenantAddonOut]:
    rows = (await db.execute(
        text(
            "SELECT ta.id, ta.addon_code, pa.display_name, ta.source, ta.status, "
            "       ta.amount, ta.starts_on, ta.ends_on, ta.note, ta.created_at, ta.cancelled_at "
            "FROM tenant_addons ta "
            "JOIN platform_addons pa ON pa.code = ta.addon_code "
            "WHERE ta.tenant_id = :tid "
            "ORDER BY (ta.status = 'ACTIVE') DESC, ta.created_at DESC"
        ),
        {"tid": str(tenant_id)},
    )).fetchall()
    return [
        TenantAddonOut(
            id=str(r.id), addon_code=r.addon_code, display_name=r.display_name,
            source=r.source, status=r.status, amount=r.amount,
            starts_on=r.starts_on.isoformat(), ends_on=_dt(r.ends_on), note=r.note,
            created_at=r.created_at.isoformat(), cancelled_at=_dt(r.cancelled_at),
        )
        for r in rows
    ]


# ── TA self-service — fixed paths ────────────────────────────────────────────

@router.get("/me/subscription", response_model=SuccessResponse[SubscriptionOut])
@require_permission(PERMISSIONS.BILLING_VIEW_OWN)
async def get_my_subscription(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[SubscriptionOut]:
    """TA: read-only view of its own tenant's subscription + payment history."""
    if not user or not user.tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context")
    return SuccessResponse(data=await _load_subscription_view(db, str(user.tenant_id)))


@router.get("/me/addons", response_model=SuccessResponse[list[TenantAddonOut]])
@require_permission(PERMISSIONS.BILLING_VIEW_OWN)
async def get_my_addons(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[list[TenantAddonOut]]:
    """TA: read-only view of its own tenant's add-ons (active + cancelled)."""
    if not user or not user.tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context")
    return SuccessResponse(data=await _load_tenant_addons(db, str(user.tenant_id)))


@router.get("/me/invoices/{payment_id}/checkout", response_model=SuccessResponse[CheckoutOut])
@require_permission(PERMISSIONS.BILLING_VIEW_OWN)
async def get_my_invoice_checkout(
    payment_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[CheckoutOut]:
    """TA: checkout info for a PENDING payment of its own tenant. Read-only —
    MANUAL returns instructions, STUB returns the redirect URL."""
    if not user or not user.tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context")

    payment = await _get_payment_for_tenant(db, str(payment_id), str(user.tenant_id))
    if payment.status != "PENDING":
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_PAYMENT_STATE", "message": "Payment is not PENDING"},
        )

    provider = get_provider(payment.provider)
    checkout = provider.checkout({"payment_id": str(payment.id)})
    return SuccessResponse(data=CheckoutOut(payment_id=str(payment.id), checkout=checkout))


# ── Public STUB webhook — fixed path, no JWT ─────────────────────────────────

@router.post("/public/payments/webhook/stub")
async def stub_payment_webhook(request: Request) -> dict:
    """Allowlisted in scripts/ci_drift_check.py and api-gateway's
    UNAUTHENTICATED_PATHS — no SMART JWT exists for a payment gateway's
    server-to-server callback. Signature verification IS the auth check."""
    await rate_limit_hit("stub-webhook", client_ip(request), limit=120, window_seconds=60)

    body = await request.body()
    try:
        event = get_provider("STUB").parse_webhook(request.headers, body)
    except ValueError as exc:
        code = str(exc)
        status_code = 401 if code == "INVALID_SIGNATURE" else 422
        raise HTTPException(status_code=status_code, detail={"code": code, "message": code})

    async with AsyncSessionLocal() as db:
        payment_row = (await db.execute(
            text("SELECT tenant_id FROM payments WHERE id = :pid"),
            {"pid": event.payment_id},
        )).fetchone()
        if payment_row is None:
            raise HTTPException(status_code=404, detail={"code": "PAYMENT_NOT_FOUND", "message": "Payment not found"})

        async with db.begin():
            await set_rls_context(db, str(payment_row.tenant_id), SYSTEM_ACTOR_ID)
            try:
                if event.event == "payment.succeeded":
                    result = await mark_paid(
                        db, event.payment_id, provider="STUB",
                        provider_reference=event.provider_reference,
                        recorded_by=SYSTEM_ACTOR_ID,
                        note="STUB webhook",
                    )
                else:
                    result = await mark_failed(
                        db, event.payment_id,
                        provider_reference=event.provider_reference,
                        note="STUB webhook",
                    )
            except ValueError as exc:
                raise _map_value_error(exc)

    return {"success": True, "data": result}


# ── SA management — parameterised paths ──────────────────────────────────────

@router.get("/{tenant_id}/subscription", response_model=SuccessResponse[SubscriptionOut])
@require_permission(PERMISSIONS.BILLING_VIEW)
async def get_tenant_subscription(
    tenant_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[SubscriptionOut]:
    """SA: a tenant's live (or latest) subscription with its payment history."""
    return SuccessResponse(data=await _load_subscription_view(db, str(tenant_id)))


@router.post("/{tenant_id}/invoices", status_code=201, response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.BILLING_MANAGE)
async def create_tenant_invoice(
    tenant_id: uuid.UUID,
    body: InvoiceCreateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[dict]:
    """SA: raise a new invoice for the tenant's live subscription."""
    try:
        result = await create_invoice(db, str(tenant_id), recorded_by=str(user.user_id), note=body.note)
    except ValueError as exc:
        raise _map_value_error(exc)

    await _log_tenant_activity(
        db, tenant_id, str(user.user_id),
        action="INVOICE_CREATED",
        new_value=f"payment={result['payment_id']} total={result['total']}",
        note=body.note,
    )
    return SuccessResponse(data=result)


@router.post("/{tenant_id}/payments/{payment_id}/mark-paid", response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.BILLING_MANAGE)
async def mark_tenant_payment_paid(
    tenant_id: uuid.UUID,
    payment_id: uuid.UUID,
    body: MarkPaidRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[dict]:
    """SA: mark a MANUAL payment paid — activates the subscription and
    extends the tenant's contract. A STUB payment must go through the
    provider's own webhook, not this endpoint."""
    payment = await _get_payment_for_tenant(db, str(payment_id), str(tenant_id))
    if payment.provider != "MANUAL":
        raise HTTPException(
            status_code=422,
            detail={"code": "WRONG_PROVIDER", "message": "Only MANUAL payments are marked paid here"},
        )

    paid_at = datetime.fromisoformat(body.paid_at) if body.paid_at else None
    try:
        result = await mark_paid(
            db, str(payment_id), provider="MANUAL",
            provider_reference=body.provider_reference, paid_at=paid_at,
            recorded_by=str(user.user_id), note=body.note,
        )
    except ValueError as exc:
        raise _map_value_error(exc)

    await _log_tenant_activity(
        db, tenant_id, str(user.user_id),
        action="PAYMENT_MARKED_PAID",
        new_value=f"payment={payment_id} ref={body.provider_reference or ''}",
        note=body.note,
    )
    return SuccessResponse(data=result)


@router.post("/{tenant_id}/payments/{payment_id}/cancel", response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.BILLING_MANAGE)
async def cancel_tenant_payment(
    tenant_id: uuid.UUID,
    payment_id: uuid.UUID,
    body: CancelInvoiceRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[dict]:
    """SA: cancel a PENDING invoice."""
    await _get_payment_for_tenant(db, str(payment_id), str(tenant_id))
    try:
        result = await cancel_invoice(db, str(payment_id), recorded_by=str(user.user_id), note=body.note)
    except ValueError as exc:
        raise _map_value_error(exc)

    await _log_tenant_activity(
        db, tenant_id, str(user.user_id),
        action="INVOICE_CANCELLED",
        new_value=f"payment={payment_id}",
        note=body.note,
    )
    return SuccessResponse(data=result)


@router.get("/{tenant_id}/addons", response_model=SuccessResponse[list[TenantAddonOut]])
@require_permission(PERMISSIONS.BILLING_VIEW)
async def get_tenant_addons(
    tenant_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[list[TenantAddonOut]]:
    """SA: a tenant's add-ons — active and cancelled."""
    return SuccessResponse(data=await _load_tenant_addons(db, str(tenant_id)))


@router.post("/{tenant_id}/addons", status_code=201, response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.BILLING_MANAGE)
async def grant_tenant_addon(
    tenant_id: uuid.UUID,
    body: AddonGrantRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[dict]:
    """SA: grant a free OVERRIDE or priced PURCHASED add-on to a tenant.

    OVERRIDE is free (amount=0) and requires `note`. PURCHASED is priced from
    the tenant's live subscription's billing_period, snapshotting price_id +
    amount at grant time. Either way the grant takes effect immediately via
    get_tenant_entitlements() and survives any later plan change.

    A PURCHASED grant on an ANNUAL, already-paid subscription also raises a
    PRORATION invoice for the whole remaining billing months, in this same
    transaction (CLAUDE.md §15 S11); it is blocked (409) while a PENDING
    PERIOD invoice exists for the subscription.
    """
    starts_on = date.fromisoformat(body.starts_on) if body.starts_on else None
    ends_on = date.fromisoformat(body.ends_on) if body.ends_on else None
    try:
        outcome = await apply_addon_grant_with_proration(
            db, str(tenant_id), body.addon_code, body.source,
            note=body.note, starts_on=starts_on, ends_on=ends_on,
            created_by=str(user.user_id),
        )
    except ValueError as exc:
        raise _map_value_error(exc)
    result = outcome["grant"]
    proration_invoice = outcome["proration_invoice"]

    await _log_tenant_activity(
        db, tenant_id, str(user.user_id),
        action="ADDON_GRANTED",
        new_value=f"addon={body.addon_code} source={body.source} amount={result['amount']}",
        note=body.note,
    )
    if proration_invoice is not None:
        await _log_tenant_activity(
            db, tenant_id, str(user.user_id),
            action="PRORATION_INVOICE_RAISED",
            new_value=f"payment={proration_invoice['payment_id']} total={proration_invoice['total']}",
        )
    return SuccessResponse(data={**result, "proration_invoice": proration_invoice})


@router.post("/{tenant_id}/addons/{addon_id}/cancel", response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.BILLING_MANAGE)
async def cancel_tenant_addon(
    tenant_id: uuid.UUID,
    addon_id: uuid.UUID,
    body: AddonCancelRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session_for_tenant),
) -> SuccessResponse[dict]:
    """SA: cancel an ACTIVE add-on grant. Never deletes the row."""
    try:
        result = await cancel_addon(db, str(tenant_id), str(addon_id), cancelled_by=str(user.user_id))
    except ValueError as exc:
        raise _map_value_error(exc)

    await _log_tenant_activity(
        db, tenant_id, str(user.user_id),
        action="ADDON_CANCELLED",
        new_value=f"addon={result['addon_code']}",
        note=body.note,
    )
    return SuccessResponse(data=result)
