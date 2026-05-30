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


# ── write_transfer_ledger_entry tests ────────────────────────────────────────

TRANSFER_ID  = "aaaabbbb-0000-0000-0000-000000000099"
PRODUCT_ID_2 = "bbbbbbbb-0000-0000-0000-000000000002"


@pytest.mark.unit
class TestWriteTransferLedgerEntry:

    async def test_write_transfer_ledger_idempotent(self) -> None:
        """Calling write_transfer_ledger_entry twice with identical args produces
        exactly one ledger entry.  The duplicate 409 from record_transaction is
        caught silently — no exception propagates to the caller."""
        from repositories.ledger_repo import write_transfer_ledger_entry
        from fastapi import HTTPException as FHE

        call_count = 0

        async def fake_record(_session, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise FHE(
                    status_code=409,
                    detail={"code": "DUPLICATE_TRANSACTION",
                            "idempotency_key": kwargs.get("idempotency_key")},
                )
            return "tx-idem-001"

        session = AsyncMock()

        with patch("repositories.ledger_repo.record_transaction", new=fake_record):
            await write_transfer_ledger_entry(
                session=session,
                transfer_id=TRANSFER_ID,
                transaction_type="RESERVE",
                quantity=Decimal("50"),
                warehouse_id=WAREHOUSE_ID,
                product_id=PRODUCT_ID_2,
                tenant_id=TENANT_ID,
                performed_by=USER_ID,
                status_transition="DRAFT_TO_PENDING_REVIEW",
            )
            # second call — must not raise
            await write_transfer_ledger_entry(
                session=session,
                transfer_id=TRANSFER_ID,
                transaction_type="RESERVE",
                quantity=Decimal("50"),
                warehouse_id=WAREHOUSE_ID,
                product_id=PRODUCT_ID_2,
                tenant_id=TENANT_ID,
                performed_by=USER_ID,
                status_transition="DRAFT_TO_PENDING_REVIEW",
            )

        assert call_count == 2, (
            "record_transaction must be called on each attempt "
            "so the idempotency guard inside record_transaction can fire"
        )

    async def test_write_transfer_ledger_reference_type(self) -> None:
        """record_transaction is called with reference_type='TRANSFER',
        reference_id=transfer_id, and the correct deterministic idempotency key."""
        from repositories.ledger_repo import write_transfer_ledger_entry

        session = AsyncMock()
        captured: dict = {}

        async def capture(_session, **kwargs):
            captured.update(kwargs)
            return "tx-ref-001"

        with patch("repositories.ledger_repo.record_transaction", new=capture):
            await write_transfer_ledger_entry(
                session=session,
                transfer_id=TRANSFER_ID,
                transaction_type="TRANSIT_OUT",
                quantity=Decimal("10"),
                warehouse_id=WAREHOUSE_ID,
                product_id=PRODUCT_ID_2,
                tenant_id=TENANT_ID,
                performed_by=USER_ID,
                status_transition="APPROVED_TO_ISSUED",
            )

        assert captured.get("reference_type") == "TRANSFER"
        assert captured.get("reference_id") == TRANSFER_ID
        expected_key = f"{TRANSFER_ID}:TRANSIT_OUT:APPROVED_TO_ISSUED"
        assert captured.get("idempotency_key") == expected_key, (
            f"Expected idempotency_key={expected_key!r}, "
            f"got {captured.get('idempotency_key')!r}"
        )

    async def test_write_transfer_ledger_all_types(self) -> None:
        """Every supported transaction_type is forwarded to record_transaction
        without error.  An unsupported type raises ValueError before any DB call."""
        from repositories.ledger_repo import write_transfer_ledger_entry

        supported = [
            ("RESERVE",           Decimal("50"),   "DRAFT_TO_PENDING_REVIEW"),
            ("RELEASE",           Decimal("-50"),  "PENDING_REVIEW_TO_CANCELLED"),
            ("TRANSIT_OUT",       Decimal("50"),   "APPROVED_TO_ISSUED"),
            ("TRANSIT_IN",        Decimal("50"),   "ISSUED_TO_IN_TRANSIT"),
            ("TRANSIT_CLEAR",     Decimal("-50"),  "IN_TRANSIT_TO_RECEIVED"),
            ("TRANSFER_REVERSAL", Decimal("50"),   "APPROVED_TO_CANCELLED"),
        ]

        session = AsyncMock()
        forwarded_types: list[str] = []

        async def capture(_session, **kwargs):
            forwarded_types.append(kwargs.get("transaction_type"))
            return "tx-type-001"

        with patch("repositories.ledger_repo.record_transaction", new=capture):
            for tx_type, qty, transition in supported:
                await write_transfer_ledger_entry(
                    session=session,
                    transfer_id=TRANSFER_ID,
                    transaction_type=tx_type,
                    quantity=qty,
                    warehouse_id=WAREHOUSE_ID,
                    product_id=PRODUCT_ID_2,
                    tenant_id=TENANT_ID,
                    performed_by=USER_ID,
                    status_transition=transition,
                )

        assert forwarded_types == [t for t, _, _ in supported], (
            "Not all supported types were forwarded to record_transaction"
        )

        # unsupported type must be rejected before any DB call
        with patch("repositories.ledger_repo.record_transaction", new=capture):
            with pytest.raises(ValueError, match="unsupported transaction_type"):
                await write_transfer_ledger_entry(
                    session=session,
                    transfer_id=TRANSFER_ID,
                    transaction_type="TRANSFER_OUT",  # this is a ledger type, not a transfer-event type
                    quantity=Decimal("10"),
                    warehouse_id=WAREHOUSE_ID,
                    product_id=PRODUCT_ID_2,
                    tenant_id=TENANT_ID,
                    performed_by=USER_ID,
                    status_transition="APPROVED",
                )
