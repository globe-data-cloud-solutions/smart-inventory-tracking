"""Unit tests for shared.db.rls — tenant context must be transaction-local.

A session-scoped set_config (is_local = false) survives COMMIT and stays on the
pooled connection, so the next request that checks the same connection out runs
under the previous request's tenant. These tests pin the fix: set_config is
called with is_local = true, and an after_begin listener re-applies the context
stored in session.info["rls"] at the start of every new transaction.
No real database connection is used.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

import shared.db.rls as rls

pytestmark = pytest.mark.unit

TENANT_ID = "11111111-1111-1111-1111-111111111111"
USER_ID = "22222222-2222-2222-2222-222222222222"


def _sql(call) -> str:
    return " ".join(str(call.args[0]).split())


@pytest.mark.asyncio
async def test_set_rls_context_uses_transaction_local() -> None:
    session = MagicMock()
    session.info = {}
    session.execute = AsyncMock()

    await rls.set_rls_context(session, TENANT_ID, USER_ID)

    assert session.execute.await_count >= 1
    for call in session.execute.await_args_list:
        sql = _sql(call)
        assert "set_config('app.current_tenant_id', :tid, true)" in sql
        assert "set_config('app.current_user_id', :uid, true)" in sql
        assert "false" not in sql
        assert call.args[1] == {"tid": TENANT_ID, "uid": USER_ID}
    assert session.info["rls"] == (TENANT_ID, USER_ID)


def test_after_begin_reapplies_context() -> None:
    assert event.contains(Session, "after_begin", rls._reapply_rls_context)

    sync_session = MagicMock()
    sync_session.info = {"rls": (TENANT_ID, USER_ID)}
    connection = MagicMock()

    rls._reapply_rls_context(sync_session, MagicMock(), connection)

    connection.execute.assert_called_once()
    call = connection.execute.call_args
    sql = _sql(call)
    assert "set_config('app.current_tenant_id', :tid, true)" in sql
    assert "set_config('app.current_user_id', :uid, true)" in sql
    assert call.args[1] == {"tid": TENANT_ID, "uid": USER_ID}


def test_after_begin_noop_without_context() -> None:
    sync_session = MagicMock()
    sync_session.info = {}
    connection = MagicMock()

    rls._reapply_rls_context(sync_session, MagicMock(), connection)

    connection.execute.assert_not_called()
