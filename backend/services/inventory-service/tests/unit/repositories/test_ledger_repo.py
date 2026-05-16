"""Unit tests for repositories/ledger_repo.py.

These tests verify the invariants that make ledger_repo the single permitted
writer to inventory_balances:
  1. record_transaction() always INSERTs a ledger row (never a direct balance UPDATE)
  2. Duplicate idempotency key → HTTP 409, transaction not written
  3. Outbox is written in the SAME session as the ledger INSERT
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from fastapi import HTTPException


TENANT_ID    = "10000000-0000-0000-0000-000000000001"
PRODUCT_ID   = "aaaaaaaa-0000-0000-0000-000000000001"
WAREHOUSE_ID = "20000000-0000-0000-0000-000000000001"
USER_ID      = "u-wm-01"
IDEM_KEY     = "test-idem-key-001"


def _make_session(balance: float = 100.0) -> AsyncMock:
    """Return a mock AsyncSession whose execute() simulates:
      call 0 — idempotency INSERT (rowcount=1 = success)
      call 1 — SELECT balance FOR UPDATE (returns balance row)
      call 2 — INSERT inventory_transactions
      call 3 — INSERT inventory_balances ... ON CONFLICT DO UPDATE (_update_running_balance)
      call 4 — INSERT outbox (write_to_outbox)
    """
    balance_row  = MagicMock()
    balance_row.qty = balance

    balance_result  = MagicMock()
    balance_result.fetchone.return_value = balance_row

    idem_result = MagicMock()
    idem_result.rowcount = 1        # INSERT succeeded — key is new

    generic_result = MagicMock()
    generic_result.fetchone.return_value = None

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[
        idem_result,     # idempotency INSERT
        balance_result,  # SELECT balance FOR UPDATE
        generic_result,  # INSERT inventory_transactions
        generic_result,  # INSERT inventory_balances (update_running_balance)
        generic_result,  # INSERT outbox
    ])
    return session


@pytest.mark.unit
class TestLedgerRepo:

    async def test_record_transaction_writes_ledger_not_balance_directly(self) -> None:
        """record_transaction() must INSERT into inventory_transactions and call
        _update_running_balance() — never issue a raw balance UPDATE from outside
        the dedicated writer."""
        from repositories.ledger_repo import record_transaction, _update_running_balance

        session = _make_session(balance=50.0)

        with patch("repositories.ledger_repo._update_running_balance",
                   new=AsyncMock()) as mock_balance_writer, \
             patch("repositories.ledger_repo.write_to_outbox", new=AsyncMock()):
            await record_transaction(
                session,
                tenant_id=TENANT_ID,
                transaction_type="RECEIVE",
                product_id=PRODUCT_ID,
                warehouse_id=WAREHOUSE_ID,
                quantity=Decimal("25"),
                performed_by=USER_ID,
                idempotency_key=IDEM_KEY,
            )

        # _update_running_balance must have been called exactly once
        mock_balance_writer.assert_awaited_once()
        call_kwargs = mock_balance_writer.call_args

        # Verify it was called with the correct delta (not a hardcoded raw SQL UPDATE)
        assert call_kwargs.args[4] == Decimal("25"), (
            "_update_running_balance received wrong delta"
        )

        # The session.execute calls must include an INSERT INTO inventory_transactions
        all_sql = [str(c.args[0]) for c in session.execute.call_args_list]
        assert any("INSERT INTO inventory_transactions" in sql for sql in all_sql), (
            "No INSERT INTO inventory_transactions found — ledger row was not written"
        )

        # No raw UPDATE to inventory_balances should appear outside _update_running_balance
        # (all balance writes must go through the dedicated writer, not a raw execute call)
        direct_balance_updates = [
            sql for sql in all_sql
            if "UPDATE SET quantity" in sql and "inventory_balances" in sql
        ]
        assert len(direct_balance_updates) == 0, (
            f"Direct balance UPDATE found outside _update_running_balance: "
            f"{direct_balance_updates}"
        )

    async def test_duplicate_idempotency_key_raises_409(self) -> None:
        """Replaying a request with the same idempotency key must raise HTTP 409.
        No ledger row, no balance change, no outbox event must be written."""
        from repositories.ledger_repo import record_transaction
        from shared.utils.idempotency import DuplicateTransactionError

        session = AsyncMock()

        with patch(
            "repositories.ledger_repo.check_and_register_idempotency_key",
            new=AsyncMock(side_effect=DuplicateTransactionError(IDEM_KEY)),
        ), patch(
            "repositories.ledger_repo._update_running_balance", new=AsyncMock()
        ) as mock_writer, \
        patch(
            "repositories.ledger_repo.write_to_outbox", new=AsyncMock()
        ) as mock_outbox:
            with pytest.raises(HTTPException) as exc_info:
                await record_transaction(
                    session,
                    tenant_id=TENANT_ID,
                    transaction_type="RECEIVE",
                    product_id=PRODUCT_ID,
                    warehouse_id=WAREHOUSE_ID,
                    quantity=Decimal("10"),
                    performed_by=USER_ID,
                    idempotency_key=IDEM_KEY,
                )

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["code"] == "DUPLICATE_TRANSACTION"
        assert exc_info.value.detail["idempotency_key"] == IDEM_KEY

        # Nothing else must have been called after the 409 guard
        mock_writer.assert_not_awaited()
        mock_outbox.assert_not_awaited()

    async def test_outbox_written_in_same_transaction(self) -> None:
        """write_to_outbox must be called on the same session object as the
        inventory_transactions INSERT — not on a separate session after commit."""
        from repositories.ledger_repo import record_transaction

        captured_sessions: list = []

        async def capture_write_to_outbox(sess, *args, **kwargs) -> None:
            captured_sessions.append(id(sess))

        session = _make_session(balance=200.0)
        session_id = id(session)

        with patch("repositories.ledger_repo.write_to_outbox",
                   new=AsyncMock(side_effect=capture_write_to_outbox)), \
             patch("repositories.ledger_repo._update_running_balance", new=AsyncMock()):
            await record_transaction(
                session,
                tenant_id=TENANT_ID,
                transaction_type="RECEIVE",
                product_id=PRODUCT_ID,
                warehouse_id=WAREHOUSE_ID,
                quantity=Decimal("5"),
                performed_by=USER_ID,
                idempotency_key=IDEM_KEY,
            )

        assert len(captured_sessions) == 1, "write_to_outbox must be called exactly once"
        assert captured_sessions[0] == session_id, (
            "write_to_outbox was called on a different session — "
            "outbox atomicity with ledger INSERT is broken"
        )

    async def test_stock_floor_prevents_negative_balance(self) -> None:
        """Deduction that would push balance below zero must raise HTTP 422."""
        from repositories.ledger_repo import record_transaction

        # Build a session whose _get_balance call returns 10.0.
        # check_and_register_idempotency_key is patched away, so the first
        # session.execute call goes straight to the balance SELECT — the mock
        # must reflect that order (no idempotency INSERT at position 0).
        balance_row = MagicMock()
        balance_row.qty = 10.0
        balance_result = MagicMock()
        balance_result.fetchone.return_value = balance_row

        session = AsyncMock()
        session.execute = AsyncMock(return_value=balance_result)

        with patch("repositories.ledger_repo.check_and_register_idempotency_key",
                   new=AsyncMock()), \
             patch("repositories.ledger_repo._update_running_balance",
                   new=AsyncMock()) as mock_writer:
            with pytest.raises(HTTPException) as exc_info:
                await record_transaction(
                    session,
                    tenant_id=TENANT_ID,
                    transaction_type="TRANSFER_OUT",
                    product_id=PRODUCT_ID,
                    warehouse_id=WAREHOUSE_ID,
                    quantity=Decimal("-50"),   # more than available (10)
                    performed_by=USER_ID,
                    idempotency_key=IDEM_KEY,
                )

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "INSUFFICIENT_STOCK"
        mock_writer.assert_not_awaited()
