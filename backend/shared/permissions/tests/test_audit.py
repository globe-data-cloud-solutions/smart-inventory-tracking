"""Unit tests for shared.permissions.audit.audit_log — tenant attribution for SA
decisions (audit_logs.tenant_id is NOT NULL and SA has no tenant of its own), the
platform-level no-insert path, and the never-raises contract on DB failure.

Mocked session throughout (no real DB connection)."""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.permissions.audit import audit_log

pytestmark = pytest.mark.asyncio


def _fake_db() -> AsyncMock:
    fake_db = AsyncMock()
    fake_db.execute = AsyncMock(return_value=MagicMock())
    fake_db.commit = AsyncMock()
    fake_db.__aenter__ = AsyncMock(return_value=fake_db)
    fake_db.__aexit__ = AsyncMock(return_value=None)
    return fake_db


def _user(*, tenant_id=None, user_id="u-1", role="TA") -> MagicMock:
    user = MagicMock()
    user.tenant_id, user.user_id, user.role = tenant_id, user_id, role
    return user


async def test_ta_own_tenant_row_written_under_own_tenant_id() -> None:
    """A TA acting on its own tenant — unchanged behaviour: tenant_id comes from the actor."""
    user = _user(tenant_id="tenant-ta-1", role="TA")
    db = _fake_db()

    import shared.permissions.audit as audit_module
    with patch.object(audit_module, "AsyncSessionLocal", lambda: db):
        await audit_log(user, "inventory:receive", {"warehouse_id": "wh-1"}, "GRANTED")

    db.execute.assert_called_once()
    params = db.execute.call_args.args[1]
    assert params["tenant_id"] == "tenant-ta-1"
    db.commit.assert_awaited_once()


async def test_sa_on_tenant_route_writes_row_under_target_tenant_id() -> None:
    """SA has no tenant_id; require_permission() stashes the route's path tenant_id as
    resource['target_tenant_id'] — the row must be written under THAT tenant."""
    user = _user(tenant_id=None, role="SA")
    db = _fake_db()
    resource = {"tenant_id": None, "target_tenant_id": "tenant-being-managed"}

    import shared.permissions.audit as audit_module
    with patch.object(audit_module, "AsyncSessionLocal", lambda: db):
        await audit_log(user, "tenant:manage", resource, "GRANTED")

    db.execute.assert_called_once()
    params = db.execute.call_args.args[1]
    assert params["tenant_id"] == "tenant-being-managed"


async def test_platform_level_action_with_no_resolvable_tenant_is_not_inserted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A platform-wide SA action (e.g. tier-config) has no tenant anywhere in sight —
    audit_log must NOT attempt an insert (it would violate the NOT NULL constraint);
    it logs a warning instead. platform_config_log is the durable record for these."""
    user = _user(tenant_id=None, role="SA")
    db = _fake_db()

    import shared.permissions.audit as audit_module
    with caplog.at_level(logging.WARNING), patch.object(audit_module, "AsyncSessionLocal", lambda: db):
        await audit_log(user, "platform:tier_config_edit", {}, "GRANTED")

    db.execute.assert_not_called()
    assert "platform-level decision not stored" in caplog.text
    assert "platform:tier_config_edit" in caplog.text


async def test_db_error_is_logged_and_never_raised(caplog: pytest.LogCaptureFixture) -> None:
    """A DB failure during the audit write must never propagate to the caller — only
    logged (logger.exception, not a silent `except: pass`)."""
    user = _user(tenant_id="tenant-1", role="TA")
    db = _fake_db()
    db.execute = AsyncMock(side_effect=RuntimeError("db exploded"))

    import shared.permissions.audit as audit_module
    with caplog.at_level(logging.ERROR), patch.object(audit_module, "AsyncSessionLocal", lambda: db):
        await audit_log(user, "inventory:receive", {}, "GRANTED")  # must not raise

    assert "failed to write audit_logs row" in caplog.text
