"""Unit tests for the P4 platform contact work (migration 080).

- routers.platform_contact.get_public_contact: unauthenticated, returns
  configured=false + nulls on an empty row.
- routers.platform_contact.update_platform_contact: SA-only, reason
  required, phone format validated, empty string -> NULL, per-field
  platform_config_log entries only for fields that actually changed.
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("DATABASE_READ_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("ENVIRONMENT", "local")

_TENANT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _TENANT_ROOT not in sys.path:
    sys.path.insert(0, _TENANT_ROOT)

from datetime import datetime, timezone  # noqa: E402 - sys.path/env setup above must run first
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402 - sys.path/env setup above must run first

import pytest  # noqa: E402 - sys.path/env setup above must run first
from fastapi import HTTPException  # noqa: E402 - sys.path/env setup above must run first


def _user(role: str = "SA"):
    from dependencies import UserContext

    return UserContext(user_id="u1", role=role, tenant_id=None, warehouse_id=None)


def _contact_row(**overrides) -> MagicMock:
    row = MagicMock()
    row.support_email = overrides.get("support_email")
    row.phone = overrides.get("phone")
    row.whatsapp = overrides.get("whatsapp")
    row.address_en = overrides.get("address_en")
    row.address_am = overrides.get("address_am")
    row.hours_en = overrides.get("hours_en")
    row.hours_am = overrides.get("hours_am")
    row.note_en = overrides.get("note_en")
    row.note_am = overrides.get("note_am")
    row.updated_at = overrides.get("updated_at", datetime.now(timezone.utc))
    row.updated_by = overrides.get("updated_by")
    return row


@pytest.mark.unit
class TestPublicContact:
    @pytest.mark.asyncio
    async def test_unconfigured_returns_false_and_nulls(self):
        from routers.platform_contact import get_public_contact

        empty_row = _contact_row()
        result_mock = MagicMock()
        result_mock.fetchone = MagicMock(return_value=empty_row)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        request = MagicMock()
        request.client.host = "127.0.0.1"
        request.headers = {}

        with patch("routers.platform_contact.AsyncSessionLocal") as session_factory:
            session_factory.return_value.__aenter__ = AsyncMock(return_value=db)
            session_factory.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("routers.platform_contact.rate_limit_hit", new=AsyncMock()):
                result = await get_public_contact(request=request)

        assert result.data.configured is False
        assert result.data.support_email is None
        assert result.data.phone is None
        assert result.data.address.en is None


@pytest.mark.unit
class TestUpdatePlatformContact:
    @pytest.mark.asyncio
    async def test_missing_reason_rejected(self):
        from routers.platform_contact import ContactUpdateRequest, update_platform_contact
        from shared.permissions.store import RolePermissionGrant as PermissionGrant

        caller = _user("SA")
        body = ContactUpdateRequest(support_email="support@example.com", reason="   ")
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=AssertionError("must not query the DB before validation")
        )

        grant = PermissionGrant(role="SA", action_id="platform:contact_edit", grant_type="FULL")
        with patch(
            "shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=grant)
        ):
            with patch("shared.permissions.audit.audit_log", new=AsyncMock()):
                with pytest.raises(HTTPException) as exc_info:
                    await update_platform_contact(body=body, user=caller, db=db)

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "REASON_REQUIRED"

    @pytest.mark.asyncio
    async def test_bad_phone_rejected(self):
        from routers.platform_contact import ContactUpdateRequest, update_platform_contact
        from shared.permissions.store import RolePermissionGrant as PermissionGrant

        caller = _user("SA")
        body = ContactUpdateRequest(phone="not-a-phone!!", reason="fix phone")
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=AssertionError("must not query the DB before validation")
        )

        grant = PermissionGrant(role="SA", action_id="platform:contact_edit", grant_type="FULL")
        with patch(
            "shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=grant)
        ):
            with patch("shared.permissions.audit.audit_log", new=AsyncMock()):
                with pytest.raises(HTTPException) as exc_info:
                    await update_platform_contact(body=body, user=caller, db=db)

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "INVALID_PHONE"

    @pytest.mark.asyncio
    async def test_bad_email_rejected(self):
        from routers.platform_contact import ContactUpdateRequest, update_platform_contact
        from shared.permissions.store import RolePermissionGrant as PermissionGrant

        caller = _user("SA")
        body = ContactUpdateRequest(support_email="not-an-email", reason="fix email")
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=AssertionError("must not query the DB before validation")
        )

        grant = PermissionGrant(role="SA", action_id="platform:contact_edit", grant_type="FULL")
        with patch(
            "shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=grant)
        ):
            with patch("shared.permissions.audit.audit_log", new=AsyncMock()):
                with pytest.raises(HTTPException) as exc_info:
                    await update_platform_contact(body=body, user=caller, db=db)

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "INVALID_EMAIL"

    def test_empty_string_coerced_to_none(self):
        from routers.platform_contact import ContactUpdateRequest

        body = ContactUpdateRequest(phone="   ", address_en="", reason="clear fields")
        assert body.phone is None
        assert body.address_en is None

    @pytest.mark.asyncio
    async def test_non_sa_forbidden(self):
        from routers.platform_contact import ContactUpdateRequest, update_platform_contact
        from shared.permissions.store import RolePermissionGrant as PermissionGrant

        caller = _user("TA")
        body = ContactUpdateRequest(support_email="support@example.com", reason="update")
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=AssertionError("must not query the DB when forbidden"))

        grant = PermissionGrant(role="TA", action_id="platform:contact_edit", grant_type="FULL")
        with patch(
            "shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=grant)
        ):
            with patch("shared.permissions.audit.audit_log", new=AsyncMock()):
                with pytest.raises(HTTPException) as exc_info:
                    await update_platform_contact(body=body, user=caller, db=db)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_success_updates_and_logs_only_changed_fields(self):
        from routers.platform_contact import ContactUpdateRequest, update_platform_contact
        from shared.permissions.store import RolePermissionGrant as PermissionGrant

        caller = _user("SA")
        body = ContactUpdateRequest(
            support_email="support@example.com",
            phone="+251911223344",
            reason="initial setup",
        )

        old_row = _contact_row(support_email=None, phone=None)
        select_before = MagicMock()
        select_before.fetchone = MagicMock(return_value=old_row)

        update_result = MagicMock()

        log_result_1 = MagicMock()
        log_result_2 = MagicMock()

        new_row = _contact_row(support_email="support@example.com", phone="+251911223344")
        select_after = MagicMock()
        select_after.fetchone = MagicMock(return_value=new_row)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                select_before,
                update_result,
                log_result_1,
                log_result_2,
                select_after,
            ]
        )

        grant = PermissionGrant(role="SA", action_id="platform:contact_edit", grant_type="FULL")
        with patch(
            "shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=grant)
        ):
            with patch("shared.permissions.audit.audit_log", new=AsyncMock()):
                result = await update_platform_contact(body=body, user=caller, db=db)

        assert result.data.configured is True
        assert result.data.support_email == "support@example.com"

        update_sql = str(db.execute.call_args_list[1].args[0])
        assert "UPDATE platform_contact" in update_sql

        log_calls = db.execute.call_args_list[2:4]
        for call in log_calls:
            sql = str(call.args[0])
            params = call.args[1]
            assert "INSERT INTO platform_config_log" in sql
            assert params["reason"] == "initial setup"
        logged_fields = {call.args[1]["field"] for call in log_calls}
        assert logged_fields == {"support_email", "phone"}

    @pytest.mark.asyncio
    async def test_unchanged_fields_write_no_log(self):
        from routers.platform_contact import ContactUpdateRequest, update_platform_contact
        from shared.permissions.store import RolePermissionGrant as PermissionGrant

        caller = _user("SA")
        body = ContactUpdateRequest(support_email="support@example.com", reason="no-op resubmit")

        old_row = _contact_row(support_email="support@example.com")
        select_before = MagicMock()
        select_before.fetchone = MagicMock(return_value=old_row)

        update_result = MagicMock()

        new_row = _contact_row(support_email="support@example.com")
        select_after = MagicMock()
        select_after.fetchone = MagicMock(return_value=new_row)

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[select_before, update_result, select_after])

        grant = PermissionGrant(role="SA", action_id="platform:contact_edit", grant_type="FULL")
        with patch(
            "shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=grant)
        ):
            with patch("shared.permissions.audit.audit_log", new=AsyncMock()):
                result = await update_platform_contact(body=body, user=caller, db=db)

        assert result.data.configured is True
        # Only SELECT, UPDATE, SELECT — no platform_config_log INSERT call.
        assert db.execute.await_count == 3
