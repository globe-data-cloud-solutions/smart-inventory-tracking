"""Unit test for update_tenant_profile (SA PATCH /{tenant_id}/profile): a
scheduled downgrade (S13) must log PLAN_DOWNGRADE_SCHEDULED, never
PROFILE_UPDATE_PLAN_TIER — nothing was actually applied to the tenant, so
reporting a "profile update" for plan_tier would be misleading, and the
field is also excluded from the response's "fields"/"changes".

Mocked session throughout, same style as test_me_profile_plan_lock.py — no
real DB connection required.
"""
from __future__ import annotations

import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL",      "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("DATABASE_READ_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("JWT_SECRET",        "test-secret")
os.environ.setdefault("JWT_SECRET_KEY",    "test-secret")
os.environ.setdefault("ENVIRONMENT",       "local")

_TENANT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _TENANT_ROOT not in sys.path:
    sys.path.insert(0, _TENANT_ROOT)

from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402 - sys.path/env setup above must run first

import pytest  # noqa: E402 - sys.path/env setup above must run first

pytestmark = pytest.mark.asyncio

TENANT_A = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")


def _sa_user():
    from dependencies import UserContext
    return UserContext(user_id="sa-1", role="SA", tenant_id=None, warehouse_id=None)


def _full_grant():
    grant = MagicMock()
    grant.grant_type = "FULL"
    return grant


def _tenant_row():
    row = MagicMock()
    row.id, row.name, row.organisation_type = TENANT_A, "Probe Co", "PRODUCER"
    row.default_locale, row.plan_tier = "en", "GROWTH"
    row.notes, row.industry = None, None
    row.address_line1 = row.address_line2 = None
    row.city = row.state_province = row.postal_code = row.country = None
    return row


def _result(fetchone=None):
    r = MagicMock()
    r.fetchone = MagicMock(return_value=fetchone)
    return r


async def test_scheduled_downgrade_logs_plan_downgrade_scheduled_not_profile_update() -> None:
    from routers.tenants import TenantProfileUpdateRequest, update_tenant_profile

    sa = _sa_user()
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[
        _result(fetchone=_tenant_row()),  # SELECT tenant row
        _result(),                        # UPDATE tenants SET updated_at = now()
    ])
    body = TenantProfileUpdateRequest(plan_tier="STARTER")

    scheduled = {
        "mode": "SCHEDULED", "plan_tier": "GROWTH", "scheduled_tier": "STARTER",
        "effective_at": "2027-01-15", "pending_renewal_invoice_id": None,
    }

    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()), \
         patch("routers.tenants.change_plan", new=AsyncMock(return_value=scheduled)), \
         patch("routers.tenants._log_tenant_activity", new=AsyncMock()) as mock_log:
        out = await update_tenant_profile(tenant_id=TENANT_A, body=body, user=sa, db=db)

    logged_actions = [call.kwargs["action"] for call in mock_log.call_args_list]
    assert "PLAN_DOWNGRADE_SCHEDULED" in logged_actions
    assert "PROFILE_UPDATE_PLAN_TIER" not in logged_actions

    assert out.data["mode"] == "SCHEDULED"
    assert "plan_tier" not in out.data["fields"]
    assert out.data["changes"] == 0
