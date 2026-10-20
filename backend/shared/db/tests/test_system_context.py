"""Unit tests for shared.db.rls.set_system_rls_context — background work context.

Background jobs (Celery contract checks, partition maintenance) have no user and
no single tenant. They run with an empty tenant and the SA flag on, labelled with
the task name, transaction-local like every request context.
No real database connection is used.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import shared.db.rls as rls

pytestmark = pytest.mark.unit


def _sql(call) -> str:
    return " ".join(str(call.args[0]).split())


@pytest.mark.asyncio
async def test_system_context_empty_tenant_sa_on() -> None:
    session = MagicMock()
    session.info = {}
    session.execute = AsyncMock()

    await rls.set_system_rls_context(session, "check_contracts")

    tenant_id, _user_id, is_sa = session.info["rls"]
    assert tenant_id == ""
    assert is_sa is True
    assert session.info["rls_label"] == "check_contracts"
    call = session.execute.await_args_list[-1]
    sql = _sql(call)
    assert "set_config('app.current_tenant_id', :tid, true)" in sql
    assert "set_config('app.is_sa', :sa, true)" in sql
    assert call.args[1]["tid"] == ""
    assert call.args[1]["sa"] == "on"
