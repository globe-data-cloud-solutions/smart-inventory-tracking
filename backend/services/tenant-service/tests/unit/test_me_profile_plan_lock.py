"""Unit tests for S12: package/plan changes are SA-only.

PATCH /api/v1/tenants/me/profile must reject a body containing any
plan/billing field (plan_tier, max_warehouses, max_users, sku_cap,
feature_flags, billing_period) with 403 PLAN_CHANGE_SA_ONLY BEFORE any
write — even though TAProfileUpdateRequest has no field for them, so
Pydantic would otherwise silently drop them. Every other profile field
(default_locale) keeps working exactly as before.

Mocked session + mocked Request/db throughout — no real DB connection
required.
"""

from __future__ import annotations

import os
import sys
import uuid

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


def _user():
    from dependencies import UserContext

    return UserContext(user_id="u-1", role="TA", tenant_id=str(TENANT_A), warehouse_id=None)


def _full_grant():
    grant = MagicMock()
    grant.grant_type = "FULL"
    return grant


def _request(raw_body: dict) -> AsyncMock:
    req = AsyncMock()
    req.json = AsyncMock(return_value=raw_body)
    return req


def _scalar_result(value):
    r = MagicMock()
    r.scalar.return_value = value
    return r


@pytest.mark.parametrize(
    "raw_body",
    [
        {"plan_tier": "GROWTH"},
        {"max_warehouses": 10},
        {"max_users": 5},
        {"sku_cap": 1000},
        {"feature_flags": {"LOGISTICS": True}},
        {"billing_period": "ANNUAL"},
        {"default_locale": "am", "plan_tier": "GROWTH"},
    ],
)
async def test_plan_billing_field_rejected_before_any_write(raw_body: dict) -> None:
    from routers.tenants import TAProfileUpdateRequest, update_my_profile

    ta = _user()
    db = AsyncMock()
    with (
        patch(
            "shared.permissions.middleware.get_role_permission",
            new=AsyncMock(return_value=_full_grant()),
        ),
        patch("shared.permissions.middleware.audit_log", new=AsyncMock()),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await update_my_profile(
                request=_request(raw_body),
                body=TAProfileUpdateRequest(
                    **{k: v for k, v in raw_body.items() if k == "default_locale"}
                ),
                user=ta,
                db=db,
            )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "PLAN_CHANGE_SA_ONLY"
    db.execute.assert_not_called()


async def test_locale_only_change_still_works() -> None:
    from routers.tenants import TAProfileUpdateRequest, update_my_profile

    ta = _user()
    db = AsyncMock()
    db.execute.return_value = _scalar_result("en")
    with (
        patch(
            "shared.permissions.middleware.get_role_permission",
            new=AsyncMock(return_value=_full_grant()),
        ),
        patch("shared.permissions.middleware.audit_log", new=AsyncMock()),
        patch("routers.tenants._log_tenant_activity", new=AsyncMock()),
    ):
        out = await update_my_profile(
            request=_request({"default_locale": "am"}),
            body=TAProfileUpdateRequest(default_locale="am"),
            user=ta,
            db=db,
        )

    assert out.data == {"default_locale": "am"}
    # One SELECT (old locale) + one UPDATE
    assert db.execute.call_count == 2


async def test_no_locale_field_returns_zero_changes() -> None:
    from routers.tenants import TAProfileUpdateRequest, update_my_profile

    ta = _user()
    db = AsyncMock()
    with (
        patch(
            "shared.permissions.middleware.get_role_permission",
            new=AsyncMock(return_value=_full_grant()),
        ),
        patch("shared.permissions.middleware.audit_log", new=AsyncMock()),
    ):
        out = await update_my_profile(
            request=_request({}),
            body=TAProfileUpdateRequest(),
            user=ta,
            db=db,
        )

    assert out.data == {"changes": 0}
    db.execute.assert_not_called()
