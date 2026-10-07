"""Permission + routing tests for routers.billing: SA full access, TA
read-only on its own tenant, tenant isolation on payment lookups, and the
public STUB webhook's signature check + idempotent replay.

Business logic (invoice math, mark_paid state transitions, VAT) is already
unit tested in backend/shared/billing/tests/test_payments.py. These tests
mock create_invoice/mark_paid/cancel_invoice/_load_subscription_view and
focus on what is specific to the route handlers: RBAC/ABAC enforcement,
tenant-isolated 404s, and webhook wiring. Mocked session + mocked permission
store throughout — no real DB connection required."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL",      "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("DATABASE_READ_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("JWT_SECRET",        "test-secret")
os.environ.setdefault("JWT_SECRET_KEY",    "test-secret")
os.environ.setdefault("ENVIRONMENT",       "local")
os.environ.setdefault("REDIS_URL",         "redis://localhost:6379/0")

_TENANT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _TENANT_ROOT not in sys.path:
    sys.path.insert(0, _TENANT_ROOT)

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

pytestmark = pytest.mark.asyncio

TENANT_A = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
TENANT_B = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")


def _user(role: str, tenant_id: str | None):
    from dependencies import UserContext
    return UserContext(user_id="u-1", role=role, tenant_id=tenant_id, warehouse_id=None)


def _full_grant():
    grant = MagicMock()
    grant.grant_type = "FULL"
    return grant


def _result(fetchone=None):
    result = MagicMock()
    result.fetchone = MagicMock(return_value=fetchone)
    return result


def _make_async_session_local(execute_side_effect):
    """A fake AsyncSessionLocal() instance supporting both
    `async with AsyncSessionLocal() as db:` and `async with db.begin():`."""
    fake_db = AsyncMock()
    fake_db.execute = AsyncMock(side_effect=execute_side_effect)
    fake_db.__aenter__ = AsyncMock(return_value=fake_db)
    fake_db.__aexit__ = AsyncMock(return_value=None)

    begin_cm = AsyncMock()
    begin_cm.__aenter__ = AsyncMock(return_value=None)
    begin_cm.__aexit__ = AsyncMock(return_value=None)
    fake_db.begin = MagicMock(return_value=begin_cm)
    return fake_db


# ── SA vs TA — /{tenant_id}/subscription (billing:view) ──────────────────────

async def test_sa_get_subscription_allowed() -> None:
    from routers.billing import get_tenant_subscription

    sa = _user("SA", None)
    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()), \
         patch("routers.billing._load_subscription_view", new=AsyncMock(return_value="SUBSCRIPTION_VIEW")):
        out = await get_tenant_subscription(tenant_id=TENANT_A, user=sa, db=AsyncMock())

    assert out.data == "SUBSCRIPTION_VIEW"


async def test_ta_get_subscription_denied_rbac() -> None:
    """TA lacks billing:view (platform_only) — RBAC_DENIED before the ABAC
    platform_only check even runs."""
    from routers.billing import get_tenant_subscription

    ta = _user("TA", str(TENANT_A))
    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=None)), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc_info:
            await get_tenant_subscription(tenant_id=TENANT_A, user=ta, db=AsyncMock())

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "RBAC_DENIED"


async def test_ta_with_billing_view_grant_still_denied_platform_only() -> None:
    """Even if a role somehow held a FULL grant for billing:view, platform_only
    still blocks every role except SA — defence in depth at the ABAC layer."""
    from routers.billing import get_tenant_subscription

    ta = _user("TA", str(TENANT_A))
    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc_info:
            await get_tenant_subscription(tenant_id=TENANT_A, user=ta, db=AsyncMock())

    assert exc_info.value.status_code == 403
    assert "platform_only" in exc_info.value.detail["code"]


# ── TA /me/subscription (billing:view_own) ────────────────────────────────────

async def test_ta_me_subscription_allowed() -> None:
    from routers.billing import get_my_subscription

    ta = _user("TA", str(TENANT_A))
    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()), \
         patch("routers.billing._load_subscription_view", new=AsyncMock(return_value="MY_SUBSCRIPTION")):
        out = await get_my_subscription(user=ta, db=AsyncMock())

    assert out.data == "MY_SUBSCRIPTION"


async def test_me_subscription_without_tenant_context_403() -> None:
    from routers.billing import get_my_subscription

    sa_with_no_tenant = _user("TA", None)
    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc_info:
            await get_my_subscription(user=sa_with_no_tenant, db=AsyncMock())

    assert exc_info.value.status_code == 403


# ── SA invoice/payment management (billing:manage) ────────────────────────────

async def test_sa_create_invoice_allowed() -> None:
    from routers.billing import InvoiceCreateRequest, create_tenant_invoice

    sa = _user("SA", None)
    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()), \
         patch("routers.billing.create_invoice", new=AsyncMock(return_value={"payment_id": "p-1", "total": "230.00"})), \
         patch("routers.billing._log_tenant_activity", new=AsyncMock()):
        out = await create_tenant_invoice(
            tenant_id=TENANT_A, body=InvoiceCreateRequest(note=None), user=sa, db=AsyncMock(),
        )

    assert out.data["payment_id"] == "p-1"


async def test_ta_create_invoice_denied_rbac() -> None:
    from routers.billing import InvoiceCreateRequest, create_tenant_invoice

    ta = _user("TA", str(TENANT_A))
    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=None)), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc_info:
            await create_tenant_invoice(
                tenant_id=TENANT_A, body=InvoiceCreateRequest(note=None), user=ta, db=AsyncMock(),
            )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "RBAC_DENIED"


async def test_sa_create_invoice_already_pending_maps_to_409() -> None:
    from routers.billing import InvoiceCreateRequest, create_tenant_invoice

    sa = _user("SA", None)
    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()), \
         patch("routers.billing.create_invoice", new=AsyncMock(side_effect=ValueError("INVOICE_ALREADY_PENDING"))):
        with pytest.raises(HTTPException) as exc_info:
            await create_tenant_invoice(
                tenant_id=TENANT_A, body=InvoiceCreateRequest(note=None), user=sa, db=AsyncMock(),
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "INVOICE_ALREADY_PENDING"


async def test_sa_mark_paid_other_tenants_payment_404() -> None:
    """The payment exists but belongs to TENANT_B — looking it up under
    TENANT_A's path must 404, never leak or act on another tenant's payment."""
    from routers.billing import MarkPaidRequest, mark_tenant_payment_paid

    sa = _user("SA", None)
    payment_row = MagicMock(id="payment-1", tenant_id=str(TENANT_B), provider="MANUAL", status="PENDING")
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_result(fetchone=payment_row))

    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc_info:
            await mark_tenant_payment_paid(
                tenant_id=TENANT_A, payment_id=uuid.uuid4(), body=MarkPaidRequest(), user=sa, db=db,
            )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["code"] == "PAYMENT_NOT_FOUND"


async def test_sa_mark_paid_stub_payment_wrong_provider_422() -> None:
    from routers.billing import MarkPaidRequest, mark_tenant_payment_paid

    sa = _user("SA", None)
    payment_row = MagicMock(id="payment-1", tenant_id=str(TENANT_A), provider="STUB", status="PENDING")
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_result(fetchone=payment_row))

    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc_info:
            await mark_tenant_payment_paid(
                tenant_id=TENANT_A, payment_id=uuid.uuid4(), body=MarkPaidRequest(), user=sa, db=db,
            )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "WRONG_PROVIDER"


async def test_sa_cancel_other_tenants_payment_404() -> None:
    from routers.billing import CancelInvoiceRequest, cancel_tenant_payment

    sa = _user("SA", None)
    payment_row = MagicMock(id="payment-1", tenant_id=str(TENANT_B), provider="MANUAL", status="PENDING")
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_result(fetchone=payment_row))

    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc_info:
            await cancel_tenant_payment(
                tenant_id=TENANT_A, payment_id=uuid.uuid4(), body=CancelInvoiceRequest(note="n/a"), user=sa, db=db,
            )

    assert exc_info.value.status_code == 404


async def test_ta_cannot_mark_paid_rbac() -> None:
    from routers.billing import MarkPaidRequest, mark_tenant_payment_paid

    ta = _user("TA", str(TENANT_A))
    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=None)), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc_info:
            await mark_tenant_payment_paid(
                tenant_id=TENANT_A, payment_id=uuid.uuid4(), body=MarkPaidRequest(), user=ta, db=AsyncMock(),
            )

    assert exc_info.value.status_code == 403


# ── Tenant add-ons (S10, billing:manage / billing:view / billing:view_own) ───

async def test_sa_grant_tenant_addon_allowed() -> None:
    from routers.billing import AddonGrantRequest, grant_tenant_addon

    sa = _user("SA", None)
    body = AddonGrantRequest(addon_code="LOGISTICS", source="OVERRIDE", note="pilot customer")
    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()), \
         patch("routers.billing.apply_addon_grant_with_proration", new=AsyncMock(
             return_value={
                 "grant": {"id": "ta-1", "addon_code": "LOGISTICS", "source": "OVERRIDE",
                           "status": "ACTIVE", "amount": "0", "price_id": None},
                 "proration_invoice": None,
             })), \
         patch("routers.billing._log_tenant_activity", new=AsyncMock()):
        out = await grant_tenant_addon(tenant_id=TENANT_A, body=body, user=sa, db=AsyncMock())

    assert out.data["addon_code"] == "LOGISTICS"
    assert out.data["proration_invoice"] is None


async def test_ta_grant_tenant_addon_denied_rbac() -> None:
    from routers.billing import AddonGrantRequest, grant_tenant_addon

    ta = _user("TA", str(TENANT_A))
    body = AddonGrantRequest(addon_code="LOGISTICS", source="OVERRIDE", note="x")
    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=None)), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc_info:
            await grant_tenant_addon(tenant_id=TENANT_A, body=body, user=ta, db=AsyncMock())

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "RBAC_DENIED"


async def test_sa_grant_tenant_addon_feature_already_in_package_422() -> None:
    from routers.billing import AddonGrantRequest, grant_tenant_addon

    sa = _user("SA", None)
    body = AddonGrantRequest(addon_code="LOT_TRACEABILITY", source="OVERRIDE", note="x")
    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()), \
         patch("routers.billing.apply_addon_grant_with_proration",
               new=AsyncMock(side_effect=ValueError("FEATURE_ALREADY_IN_PACKAGE"))):
        with pytest.raises(HTTPException) as exc_info:
            await grant_tenant_addon(tenant_id=TENANT_A, body=body, user=sa, db=AsyncMock())

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "FEATURE_ALREADY_IN_PACKAGE"


async def test_sa_grant_tenant_addon_already_active_409() -> None:
    from routers.billing import AddonGrantRequest, grant_tenant_addon

    sa = _user("SA", None)
    body = AddonGrantRequest(addon_code="LOGISTICS", source="OVERRIDE", note="x")
    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()), \
         patch("routers.billing.apply_addon_grant_with_proration",
               new=AsyncMock(side_effect=ValueError("ADDON_ALREADY_ACTIVE"))):
        with pytest.raises(HTTPException) as exc_info:
            await grant_tenant_addon(tenant_id=TENANT_A, body=body, user=sa, db=AsyncMock())

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "ADDON_ALREADY_ACTIVE"


async def test_sa_grant_tenant_addon_blocked_pending_period_invoice_409() -> None:
    """S11: a PURCHASED grant blocked by a PENDING PERIOD invoice -> 409
    INVOICE_PENDING_SETTLE_FIRST, same _map_value_error path as the other
    ValueError codes above."""
    from routers.billing import AddonGrantRequest, grant_tenant_addon

    sa = _user("SA", None)
    body = AddonGrantRequest(addon_code="LOGISTICS", source="PURCHASED")
    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()), \
         patch("routers.billing.apply_addon_grant_with_proration",
               new=AsyncMock(side_effect=ValueError("INVOICE_PENDING_SETTLE_FIRST"))):
        with pytest.raises(HTTPException) as exc_info:
            await grant_tenant_addon(tenant_id=TENANT_A, body=body, user=sa, db=AsyncMock())

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "INVOICE_PENDING_SETTLE_FIRST"


async def test_sa_cancel_tenant_addon_allowed() -> None:
    from routers.billing import AddonCancelRequest, cancel_tenant_addon

    sa = _user("SA", None)
    body = AddonCancelRequest(note="no longer needed")
    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()), \
         patch("routers.billing.cancel_addon", new=AsyncMock(
             return_value={"id": "ta-1", "addon_code": "LOGISTICS", "status": "CANCELLED"})), \
         patch("routers.billing._log_tenant_activity", new=AsyncMock()):
        out = await cancel_tenant_addon(tenant_id=TENANT_A, addon_id=uuid.uuid4(), body=body, user=sa, db=AsyncMock())

    assert out.data["status"] == "CANCELLED"


async def test_ta_cancel_tenant_addon_denied_rbac() -> None:
    from routers.billing import AddonCancelRequest, cancel_tenant_addon

    ta = _user("TA", str(TENANT_A))
    body = AddonCancelRequest(note="x")
    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=None)), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc_info:
            await cancel_tenant_addon(tenant_id=TENANT_A, addon_id=uuid.uuid4(), body=body, user=ta, db=AsyncMock())

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "RBAC_DENIED"


async def test_sa_get_tenant_addons_allowed() -> None:
    from routers.billing import get_tenant_addons

    sa = _user("SA", None)
    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()), \
         patch("routers.billing._load_tenant_addons", new=AsyncMock(return_value=[])):
        out = await get_tenant_addons(tenant_id=TENANT_A, user=sa, db=AsyncMock())

    assert out.data == []


async def test_ta_get_my_addons_allowed() -> None:
    from routers.billing import get_my_addons

    ta = _user("TA", str(TENANT_A))
    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()), \
         patch("routers.billing._load_tenant_addons", new=AsyncMock(return_value=[])):
        out = await get_my_addons(user=ta, db=AsyncMock())

    assert out.data == []


async def test_ta_get_tenant_addons_denied_rbac() -> None:
    """TA lacks billing:view (platform_only) on the by-tenant endpoint —
    must use GET /me/addons instead."""
    from routers.billing import get_tenant_addons

    ta = _user("TA", str(TENANT_A))
    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=None)), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc_info:
            await get_tenant_addons(tenant_id=TENANT_A, user=ta, db=AsyncMock())

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "RBAC_DENIED"


# ── Public STUB webhook ───────────────────────────────────────────────────────

def _fake_request(headers: dict, body: bytes):
    req = MagicMock()
    req.headers = headers
    req.body = AsyncMock(return_value=body)
    req.client = MagicMock(host="1.2.3.4")
    return req


def _signed(secret: str, payload: dict) -> tuple[bytes, str]:
    body = json.dumps(payload).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, sig


async def test_webhook_bad_signature_401() -> None:
    from routers.billing import stub_payment_webhook

    with patch.dict(os.environ, {"STUB_WEBHOOK_SECRET": "s5-local-secret"}), \
         patch("routers.billing.rate_limit_hit", new=AsyncMock()):
        body, _ = _signed("s5-local-secret", {"event": "payment.succeeded", "payment_id": "p-1"})
        request = _fake_request({"X-Stub-Signature": "0" * 64}, body)
        with pytest.raises(HTTPException) as exc_info:
            await stub_payment_webhook(request)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["code"] == "INVALID_SIGNATURE"


async def test_webhook_unknown_payment_404() -> None:
    from routers.billing import stub_payment_webhook

    body, sig = _signed("s5-local-secret", {"event": "payment.succeeded", "payment_id": "unknown-payment"})
    request = _fake_request({"X-Stub-Signature": sig}, body)

    fake_session = _make_async_session_local([_result(fetchone=None)])  # payment lookup -> None

    with patch.dict(os.environ, {"STUB_WEBHOOK_SECRET": "s5-local-secret"}), \
         patch("routers.billing.rate_limit_hit", new=AsyncMock()), \
         patch("routers.billing.AsyncSessionLocal", side_effect=lambda: fake_session):
        with pytest.raises(HTTPException) as exc_info:
            await stub_payment_webhook(request)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["code"] == "PAYMENT_NOT_FOUND"


async def test_webhook_duplicate_delivery_is_idempotent_200() -> None:
    """A second delivery of the same succeeded event: mark_paid() is itself
    idempotent (already_paid=True) — the webhook must return 200, not error,
    so the gateway doesn't retry forever."""
    from routers.billing import stub_payment_webhook

    body, sig = _signed("s5-local-secret", {
        "event": "payment.succeeded", "payment_id": "payment-1", "provider_reference": "STUB-REF-1",
    })
    request = _fake_request({"X-Stub-Signature": sig}, body)

    payment_row = MagicMock(tenant_id=str(TENANT_A))
    fake_session = _make_async_session_local([_result(fetchone=payment_row)])

    with patch.dict(os.environ, {"STUB_WEBHOOK_SECRET": "s5-local-secret"}), \
         patch("routers.billing.rate_limit_hit", new=AsyncMock()), \
         patch("routers.billing.AsyncSessionLocal", side_effect=lambda: fake_session), \
         patch("routers.billing.set_rls_context", new=AsyncMock()), \
         patch("routers.billing.mark_paid", new=AsyncMock(
             return_value={"payment_id": "payment-1", "status": "PAID", "already_paid": True})):
        result = await stub_payment_webhook(request)

    assert result == {"success": True, "data": {"payment_id": "payment-1", "status": "PAID", "already_paid": True}}


async def test_webhook_failed_event_calls_mark_failed() -> None:
    from routers.billing import stub_payment_webhook

    body, sig = _signed("s5-local-secret", {
        "event": "payment.failed", "payment_id": "payment-1", "provider_reference": "STUB-REF-2",
    })
    request = _fake_request({"X-Stub-Signature": sig}, body)

    payment_row = MagicMock(tenant_id=str(TENANT_A))
    fake_session = _make_async_session_local([_result(fetchone=payment_row)])

    with patch.dict(os.environ, {"STUB_WEBHOOK_SECRET": "s5-local-secret"}), \
         patch("routers.billing.rate_limit_hit", new=AsyncMock()), \
         patch("routers.billing.AsyncSessionLocal", side_effect=lambda: fake_session), \
         patch("routers.billing.set_rls_context", new=AsyncMock()), \
         patch("routers.billing.mark_failed", new=AsyncMock(
             return_value={"payment_id": "payment-1", "status": "FAILED"})) as mock_mark_failed:
        result = await stub_payment_webhook(request)

    mock_mark_failed.assert_awaited_once()
    assert result["data"]["status"] == "FAILED"
