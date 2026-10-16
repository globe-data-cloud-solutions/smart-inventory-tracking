"""Unit tests for shared.permissions.audit.audit_log — tenant attribution for SA
decisions (audit_logs.tenant_id is NOT NULL and SA has no tenant of its own), the
platform-level no-insert path, and the never-raises contract on DB failure.

Mocked session throughout (no real DB connection)."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
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


async def test_resource_with_uuid_and_datetime_serializes_without_error() -> None:
    """abac_context frequently carries raw UUID/datetime values (e.g. warehouse_id,
    occurred_at) copied straight from ORM objects — json.dumps must not raise on
    those or the row is silently dropped (caught by the except Exception below,
    never reaching the INSERT)."""
    user = _user(tenant_id="tenant-1", role="TA")
    db = _fake_db()
    resource = {
        "warehouse_id": uuid.uuid4(),
        "occurred_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }

    import shared.permissions.audit as audit_module
    with patch.object(audit_module, "AsyncSessionLocal", lambda: db):
        await audit_log(user, "inventory:receive", resource, "GRANTED")

    db.execute.assert_called_once()
    params = db.execute.call_args.args[1]
    assert "abac_context" in params


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


async def test_caller_session_row_inserted_on_that_session_without_commit() -> None:
    """db given: the INSERT runs on the caller's session, AsyncSessionLocal is never
    opened, and nothing is committed here — the caller's transaction owns the commit."""
    user = _user(tenant_id="tenant-1", role="TA")
    caller_db = _fake_db()
    own_session = MagicMock()

    import shared.permissions.audit as audit_module
    with patch.object(audit_module, "AsyncSessionLocal", own_session):
        await audit_log(user, "adjustment:approve", {"resource_id": "a-1"}, "GRANTED", db=caller_db)

    caller_db.execute.assert_awaited_once()
    assert caller_db.execute.call_args.args[1]["tenant_id"] == "tenant-1"
    caller_db.commit.assert_not_called()
    own_session.assert_not_called()


async def test_caller_session_error_propagates() -> None:
    """db given: a failed INSERT must raise so the caller's business write rolls back
    with it — an audit failure is never swallowed in this mode."""
    user = _user(tenant_id="tenant-1", role="TA")
    caller_db = _fake_db()
    caller_db.execute = AsyncMock(side_effect=RuntimeError("db exploded"))

    with pytest.raises(RuntimeError, match="db exploded"):
        await audit_log(user, "adjustment:approve", {}, "GRANTED", db=caller_db)


async def test_caller_session_platform_level_action_is_not_inserted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """db given but no resolvable tenant: same no-insert warning rule as the default path."""
    user = _user(tenant_id=None, role="SA")
    caller_db = _fake_db()

    with caplog.at_level(logging.WARNING):
        await audit_log(user, "platform:tier_config_edit", {}, "GRANTED", db=caller_db)

    caller_db.execute.assert_not_called()
    assert "platform-level decision not stored" in caplog.text


async def test_default_path_still_uses_own_session_and_commits() -> None:
    """db None: behaviour unchanged — own AsyncSessionLocal session, committed once."""
    user = _user(tenant_id="tenant-1", role="TA")
    own = _fake_db()

    import shared.permissions.audit as audit_module
    with patch.object(audit_module, "AsyncSessionLocal", lambda: own):
        await audit_log(user, "inventory:receive", {}, "DENIED", "RBAC_DENIED")

    own.execute.assert_awaited_once()
    own.commit.assert_awaited_once()
