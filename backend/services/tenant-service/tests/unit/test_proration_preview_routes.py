"""Unit tests for the proration-preview route:
GET /{tenant_id}/proration-preview (SA, tenant:manage + inline SA check).

GET /me/proration-preview (the TA-side preview) was removed in S12 — no UI
ever called it (CLAUDE.md §15 S12); package/plan changes are SA-only now.

Mocked session + mocked permission store throughout — no real DB
connection required. preview_upgrade()/preview_addon() (shared.billing.
proration) already have their own direct unit tests
(backend/shared/billing/tests/test_proration.py); these tests only verify
routing: permission gates, exactly-one-of-tier/addon validation, and
Decimal/date serialization.
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import date
from decimal import Decimal

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("DATABASE_READ_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("ENVIRONMENT", "local")

_TENANT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _TENANT_ROOT not in sys.path:
    sys.path.insert(0, _TENANT_ROOT)

from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402 - sys.path/env setup above must run first

import pytest  # noqa: E402 - sys.path/env setup above must run first
from fastapi import HTTPException  # noqa: E402 - sys.path/env setup above must run first

pytestmark = pytest.mark.asyncio

TENANT_A = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")


def _user(role: str, tenant_id: str | None):
    from dependencies import UserContext

    return UserContext(user_id="u-1", role=role, tenant_id=tenant_id, warehouse_id=None)


def _full_grant():
    grant = MagicMock()
    grant.grant_type = "FULL"
    return grant


_PREVIEW = {
    "remaining_months": 7,
    "free_until": date(2026, 6, 15),
    "period_end": date(2027, 1, 15),
    "old_amount": Decimal("1000.00"),
    "new_amount": Decimal("2200.00"),
    "subtotal": Decimal("700.00"),
    "vat": Decimal("105.00"),
    "total": Decimal("805.00"),
    "currency": "ETB",
    "will_invoice": True,
    "blocked_code": None,
}


async def test_sa_proration_preview_for_any_tenant() -> None:
    from routers.tenants import get_tenant_proration_preview

    sa = _user("SA", None)
    with (
        patch(
            "shared.permissions.middleware.get_role_permission",
            new=AsyncMock(return_value=_full_grant()),
        ),
        patch("shared.permissions.middleware.audit_log", new=AsyncMock()),
        patch(
            "routers.tenants.preview_upgrade", new=AsyncMock(return_value=_PREVIEW)
        ) as mock_preview,
    ):
        out = await get_tenant_proration_preview(
            tenant_id=TENANT_A, tier="GROWTH", addon=None, user=sa, db=AsyncMock()
        )

    assert mock_preview.call_args.args[1] == str(TENANT_A)
    assert out.data["will_invoice"] is True


async def test_sa_proration_preview_denied_for_non_sa() -> None:
    """TENANT_MANAGE RBAC passes, but the inline SA-only check must still
    reject a non-SA caller (same pattern as GET /{tenant_id}/plan)."""
    from routers.tenants import get_tenant_proration_preview

    ta = _user("TA", str(TENANT_A))
    with (
        patch(
            "shared.permissions.middleware.get_role_permission",
            new=AsyncMock(return_value=_full_grant()),
        ),
        patch("shared.permissions.middleware.audit_log", new=AsyncMock()),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await get_tenant_proration_preview(
                tenant_id=TENANT_A, tier="GROWTH", addon=None, user=ta, db=AsyncMock()
            )

    assert exc_info.value.status_code == 403
    # Refused by the permission layer (platform_only action), before the handler.
    assert exc_info.value.detail["code"] == "ABAC_DENIED"
    assert exc_info.value.detail["reason"] == "platform_only"
