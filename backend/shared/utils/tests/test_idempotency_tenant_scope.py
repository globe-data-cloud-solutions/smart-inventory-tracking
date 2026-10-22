"""Unit tests for shared.utils.idempotency tenant scoping (migration 094).

Keys are unique per (tenant_id, idempotency_key). Two tenants may use the same
key, and a lookup without a tenant never reads another tenant's keys.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from shared.utils.idempotency import (
    DuplicateTransactionError,
    check_and_register_idempotency_key,
    idempotency_key_exists,
)

TENANT_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TX_ID = "11111111-1111-1111-1111-111111111111"


def _session(rowcount: int = 1, fetch=None) -> MagicMock:
    session = MagicMock()
    result = MagicMock()
    result.rowcount = rowcount
    result.fetchone.return_value = fetch
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.mark.asyncio
async def test_register_inserts_with_tenant_and_conflicts_on_tenant_key() -> None:
    session = _session(rowcount=1)
    await check_and_register_idempotency_key(session, TENANT_A, "k-1", TX_ID)
    sql = str(session.execute.call_args.args[0].text)
    params = session.execute.call_args.args[1]
    assert "(tenant_id, idempotency_key, transaction_id)" in sql
    assert "ON CONFLICT (tenant_id, idempotency_key)" in sql
    assert params == {"tid": TENANT_A, "key": "k-1", "tx_id": TX_ID}


@pytest.mark.asyncio
async def test_register_raises_duplicate_for_same_tenant_replay() -> None:
    session = _session(rowcount=0)
    with pytest.raises(DuplicateTransactionError) as exc:
        await check_and_register_idempotency_key(session, TENANT_A, "k-1", TX_ID)
    assert exc.value.idempotency_key == "k-1"


@pytest.mark.asyncio
async def test_exists_is_tenant_scoped() -> None:
    session = _session(fetch=(1,))
    assert await idempotency_key_exists(session, TENANT_A, "k-1") is True
    sql = str(session.execute.call_args.args[0].text)
    assert "WHERE tenant_id = :tid AND idempotency_key = :key" in sql


@pytest.mark.asyncio
async def test_exists_without_tenant_never_queries() -> None:
    session = _session(fetch=(1,))
    assert await idempotency_key_exists(session, None, "k-1") is False
    session.execute.assert_not_awaited()
