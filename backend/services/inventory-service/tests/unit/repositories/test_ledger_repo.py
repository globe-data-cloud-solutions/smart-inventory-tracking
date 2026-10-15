"""Unit tests for repositories/ledger_repo.py.

These tests verify the invariants that make ledger_repo the single permitted
writer to inventory_balances:
  1. record_transaction() always INSERTs a ledger row (never a direct balance UPDATE)
  2. Duplicate idempotency key → HTTP 409, transaction not written
  3. Outbox is written in the SAME session as the ledger INSERT
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


TENANT_ID    = "10000000-0000-0000-0000-000000000001"
PRODUCT_ID   = "aaaaaaaa-0000-0000-0000-000000000001"
WAREHOUSE_ID = "20000000-0000-0000-0000-000000000001"
USER_ID      = "u-wm-01"
IDEM_KEY     = "test-idem-key-001"


def _make_session(balance: float = 100.0, batch_tracking: bool = False) -> AsyncMock:
    """Return a mock AsyncSession whose execute() simulates:
      call 0 — idempotency INSERT (rowcount=1 = success)
      call 1 — SELECT balance FOR UPDATE (returns balance row)
      call 2 — SELECT batch_tracking FROM products FOR SHARE (Step 2b lot guard)
      call 3 — INSERT inventory_transactions
      call 4 — INSERT inventory_balances ... ON CONFLICT DO UPDATE (_update_running_balance)
      call 5 — INSERT outbox (write_to_outbox)
    """
    balance_row  = MagicMock()
    balance_row.qty = balance

    balance_result  = MagicMock()
    balance_result.fetchone.return_value = balance_row

    idem_result = MagicMock()
    idem_result.rowcount = 1        # INSERT succeeded — key is new

    batch_row = MagicMock()
    batch_row.batch_tracking = batch_tracking
    batch_result = MagicMock()
    batch_result.fetchone.return_value = batch_row

    generic_result = MagicMock()
    generic_result.fetchone.return_value = None

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[
        idem_result,     # idempotency INSERT
        balance_result,  # SELECT balance FOR UPDATE
        batch_result,    # SELECT batch_tracking FOR SHARE (Step 2b)
        generic_result,  # INSERT inventory_transactions
        generic_result,  # INSERT inventory_balances (update_running_balance)
        generic_result,  # INSERT outbox
    ])
    return session


def _make_lot_session(
    balance: float = 100.0, lot_balance: float = 100.0, batch_tracking: bool = True,
) -> AsyncMock:
    """Same as _make_session but with an extra batch_tracking SELECT (Step 2b)
    and lot-balance SELECT FOR UPDATE inserted between the product balance
    lock and the ledger INSERT, for use when lot_id is given and the type is
    not neutral:
      call 0 — idempotency INSERT
      call 1 — SELECT product balance FOR UPDATE
      call 2 — SELECT batch_tracking FROM products FOR SHARE (Step 2b)
      call 3 — SELECT lot balance FOR UPDATE
      call 4 — INSERT inventory_transactions
      call 5 — INSERT inventory_balances (update_running_balance)
      call 6 — INSERT outbox
    (_update_lot_balance is patched separately, so no extra call slot is needed for it.)
    """
    balance_row = MagicMock()
    balance_row.qty = balance

    balance_result = MagicMock()
    balance_result.fetchone.return_value = balance_row

    batch_row = MagicMock()
    batch_row.batch_tracking = batch_tracking
    batch_result = MagicMock()
    batch_result.fetchone.return_value = batch_row

    lot_balance_row = MagicMock()
    lot_balance_row.qty = lot_balance

    lot_balance_result = MagicMock()
    lot_balance_result.fetchone.return_value = lot_balance_row

    idem_result = MagicMock()
    idem_result.rowcount = 1

    generic_result = MagicMock()
    generic_result.fetchone.return_value = None

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[
        idem_result,
        balance_result,
        batch_result,
        lot_balance_result,
        generic_result,
        generic_result,
        generic_result,
    ])
    return session


@pytest.mark.unit
class TestLedgerRepo:

    async def test_record_transaction_writes_ledger_not_balance_directly(self) -> None:
        """record_transaction() must INSERT into inventory_transactions and call
        _update_running_balance() — never issue a raw balance UPDATE from outside
        the dedicated writer."""
        from repositories.ledger_repo import record_transaction

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

    @pytest.mark.parametrize("transaction_type", ["RECEIVE", "ISSUE", "TRANSIT_CLEAR", "LOT_OPENING"])
    async def test_zero_quantity_raises_422_and_writes_nothing(self, transaction_type: str) -> None:
        """quantity == 0 → HTTP 422 ZERO_QUANTITY before anything else, for
        every type (balance-neutral and lot-only included): no idempotency key
        registered, no ledger row, no balance change, no outbox event."""
        from repositories.ledger_repo import record_transaction

        session = AsyncMock()

        with patch(
            "repositories.ledger_repo.check_and_register_idempotency_key", new=AsyncMock()
        ) as mock_idem, patch(
            "repositories.ledger_repo._update_running_balance", new=AsyncMock()
        ) as mock_writer, patch(
            "repositories.ledger_repo.write_to_outbox", new=AsyncMock()
        ) as mock_outbox:
            with pytest.raises(HTTPException) as exc_info:
                await record_transaction(
                    session,
                    tenant_id=TENANT_ID,
                    transaction_type=transaction_type,
                    product_id=PRODUCT_ID,
                    warehouse_id=WAREHOUSE_ID,
                    quantity=Decimal("0.0000"),
                    performed_by=USER_ID,
                    idempotency_key=IDEM_KEY,
                    lot_id="lot-1" if transaction_type == "LOT_OPENING" else None,
                )

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "ZERO_QUANTITY"
        assert exc_info.value.detail["transaction_type"] == transaction_type
        mock_idem.assert_not_awaited()
        session.execute.assert_not_awaited()
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
        balance_row.batch_tracking = False  # same mock answers the Step 2b lot-guard SELECT too
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

    async def test_reserve_does_not_affect_on_hand(self) -> None:
        """RESERVE (written at PENDING_REVIEW) must NOT call _update_running_balance.

        Root cause of Critical Bug 1: RESERVE entries went through the normal
        record_transaction path including _update_running_balance, which increased
        inventory_balances.quantity.  inventory_analytics.get_stock() reads that
        column as current_stock — so On Hand incorrectly grew at PENDING_REVIEW.

        Fix: _BALANCE_NEUTRAL_TYPES causes record_transaction to skip both the
        stock-floor check AND the balance update for RESERVE/RELEASE/TRANSIT_* types.
        """
        from repositories.ledger_repo import record_transaction

        session = _make_session(balance=100.0)

        with patch("repositories.ledger_repo._update_running_balance",
                   new=AsyncMock()) as mock_writer, \
             patch("repositories.ledger_repo.write_to_outbox", new=AsyncMock()):
            await record_transaction(
                session,
                tenant_id=TENANT_ID,
                transaction_type="RESERVE",
                product_id=PRODUCT_ID,
                warehouse_id=WAREHOUSE_ID,
                quantity=Decimal("50"),
                performed_by=USER_ID,
                idempotency_key=IDEM_KEY,
            )

        mock_writer.assert_not_awaited(), (
            "RESERVE must NOT call _update_running_balance — it is a balance-neutral "
            "audit entry and must not inflate On Hand"
        )

        # Verify same protection for all other neutral types
        for neutral_type in ("RELEASE", "TRANSIT_OUT", "TRANSIT_IN", "TRANSIT_CLEAR"):
            session2 = _make_session(balance=100.0)
            with patch("repositories.ledger_repo._update_running_balance",
                       new=AsyncMock()) as mock2, \
                 patch("repositories.ledger_repo.write_to_outbox", new=AsyncMock()):
                await record_transaction(
                    session2,
                    tenant_id=TENANT_ID,
                    transaction_type=neutral_type,
                    product_id=PRODUCT_ID,
                    warehouse_id=WAREHOUSE_ID,
                    quantity=Decimal("30"),
                    performed_by=USER_ID,
                    idempotency_key=f"{IDEM_KEY}-{neutral_type}",
                )
            mock2.assert_not_awaited(), f"{neutral_type} must not update balance"

    async def test_transfer_reversal_does_affect_on_hand(self) -> None:
        """TRANSFER_REVERSAL (at APPROVED→CANCELLED) MUST update inventory_balances.

        Unlike the other transfer-ledger types, TRANSFER_REVERSAL replaces the old
        RETURN transaction and restores on_hand after the TRANSFER_OUT deduction at APPROVED.
        It must NOT be in _BALANCE_NEUTRAL_TYPES.
        """
        from repositories.ledger_repo import record_transaction

        session = _make_session(balance=100.0)

        with patch("repositories.ledger_repo._update_running_balance",
                   new=AsyncMock()) as mock_writer, \
             patch("repositories.ledger_repo.write_to_outbox", new=AsyncMock()):
            await record_transaction(
                session,
                tenant_id=TENANT_ID,
                transaction_type="TRANSFER_REVERSAL",
                product_id=PRODUCT_ID,
                warehouse_id=WAREHOUSE_ID,
                quantity=Decimal("50"),
                performed_by=USER_ID,
                idempotency_key=f"{IDEM_KEY}-reversal",
            )

        mock_writer.assert_awaited_once(), (
            "TRANSFER_REVERSAL must call _update_running_balance to restore on_hand "
            "after APPROVED→CANCELLED"
        )

    async def test_lot_id_none_makes_same_execute_calls_as_before(self) -> None:
        """A non-lot call (lot_id=None) on a non-batch-tracked product must make
        no lot-balance calls — only the Step 2b batch_tracking lookup is added
        on top of the pre-lot-support call set."""
        from repositories.ledger_repo import record_transaction

        session = _make_session(balance=50.0, batch_tracking=False)

        with patch("repositories.ledger_repo._update_running_balance", new=AsyncMock()), \
             patch("repositories.ledger_repo._update_lot_balance", new=AsyncMock()) as mock_lot, \
             patch("repositories.ledger_repo._get_lot_balance", new=AsyncMock()) as mock_get_lot, \
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

        assert session.execute.await_count == 4, (
            "lot_id=None must not add any lot-balance session.execute calls "
            "(idempotency INSERT, balance SELECT, batch_tracking SELECT, ledger INSERT — "
            "_update_running_balance/write_to_outbox are mocked out here)"
        )
        mock_get_lot.assert_not_awaited()
        mock_lot.assert_not_awaited()

    async def test_lot_receipt_updates_both_balances(self) -> None:
        """A RECEIVE with lot_id must update both the product balance and the
        lot balance, in the same transaction."""
        from repositories.ledger_repo import record_transaction

        session = _make_lot_session(balance=100.0, lot_balance=10.0)

        with patch("repositories.ledger_repo._update_running_balance",
                   new=AsyncMock()) as mock_running, \
             patch("repositories.ledger_repo._update_lot_balance",
                   new=AsyncMock()) as mock_lot, \
             patch("repositories.ledger_repo.write_to_outbox", new=AsyncMock()):
            await record_transaction(
                session,
                tenant_id=TENANT_ID,
                transaction_type="RECEIVE",
                product_id=PRODUCT_ID,
                warehouse_id=WAREHOUSE_ID,
                quantity=Decimal("10"),
                performed_by=USER_ID,
                idempotency_key=IDEM_KEY,
                lot_id="lot-001",
                lot_number="LOT-A1",
            )

        mock_running.assert_awaited_once()
        mock_lot.assert_awaited_once()
        lot_call = mock_lot.call_args
        assert lot_call.args[2] == "lot-001"
        assert lot_call.args[5] == Decimal("10")

    async def test_lot_issue_beyond_lot_balance_raises_insufficient_lot_stock(self) -> None:
        """An ISSUE that would drive the LOT balance negative must raise
        INSUFFICIENT_LOT_STOCK even though the product-level total is enough."""
        from repositories.ledger_repo import record_transaction

        # Product total is 100 (plenty), but this lot only has 5.
        session = _make_lot_session(balance=100.0, lot_balance=5.0)

        with patch("repositories.ledger_repo._update_running_balance",
                   new=AsyncMock()) as mock_running, \
             patch("repositories.ledger_repo._update_lot_balance",
                   new=AsyncMock()) as mock_lot, \
             patch("repositories.ledger_repo.write_to_outbox", new=AsyncMock()):
            with pytest.raises(HTTPException) as exc_info:
                await record_transaction(
                    session,
                    tenant_id=TENANT_ID,
                    transaction_type="ISSUE",
                    product_id=PRODUCT_ID,
                    warehouse_id=WAREHOUSE_ID,
                    quantity=Decimal("-10"),
                    performed_by=USER_ID,
                    idempotency_key=IDEM_KEY,
                    lot_id="lot-001",
                )

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "INSUFFICIENT_LOT_STOCK"
        mock_running.assert_not_awaited()
        mock_lot.assert_not_awaited()

    async def test_neutral_type_with_lot_id_writes_ledger_row_not_lot_balance(self) -> None:
        """A balance-neutral type (e.g. RESERVE) with lot_id must still write the
        lot columns onto the ledger row, but must never touch lot_balances."""
        from repositories.ledger_repo import record_transaction

        session = _make_session(balance=100.0)

        with patch("repositories.ledger_repo._update_running_balance",
                   new=AsyncMock()) as mock_running, \
             patch("repositories.ledger_repo._update_lot_balance",
                   new=AsyncMock()) as mock_lot, \
             patch("repositories.ledger_repo._get_lot_balance",
                   new=AsyncMock()) as mock_get_lot, \
             patch("repositories.ledger_repo.write_to_outbox", new=AsyncMock()):
            await record_transaction(
                session,
                tenant_id=TENANT_ID,
                transaction_type="RESERVE",
                product_id=PRODUCT_ID,
                warehouse_id=WAREHOUSE_ID,
                quantity=Decimal("50"),
                performed_by=USER_ID,
                idempotency_key=IDEM_KEY,
                lot_id="lot-001",
                lot_number="LOT-A1",
            )

        mock_get_lot.assert_not_awaited()
        mock_lot.assert_not_awaited()
        mock_running.assert_not_awaited()

        all_sql = [str(c.args[0]) for c in session.execute.call_args_list]
        assert any("INSERT INTO inventory_transactions" in sql for sql in all_sql)

        ledger_call = session.execute.call_args_list[2]
        assert ledger_call.args[1]["lot_id"] == "lot-001"
        assert ledger_call.args[1]["lot_number"] == "LOT-A1"

    async def test_lot_columns_passed_into_insert_params(self) -> None:
        """The inventory_transactions INSERT must carry lot_id/lot_number/expiry_date
        (NULL when not given)."""
        from repositories.ledger_repo import record_transaction

        session = _make_session(balance=100.0)

        with patch("repositories.ledger_repo._update_running_balance", new=AsyncMock()), \
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

        ledger_call = session.execute.call_args_list[3]
        assert ledger_call.args[1]["lot_id"] is None
        assert ledger_call.args[1]["lot_number"] is None
        assert ledger_call.args[1]["expiry_date"] is None

    async def test_source_and_unit_cost_default_to_web_and_none(self) -> None:
        """With no source/unit_cost given, the ledger INSERT must carry the
        same defaults as before these params existed."""
        from repositories.ledger_repo import record_transaction

        session = _make_session(balance=100.0)

        with patch("repositories.ledger_repo._update_running_balance", new=AsyncMock()), \
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

        ledger_call = session.execute.call_args_list[3]
        assert ledger_call.args[1]["source"] == "WEB"
        assert ledger_call.args[1]["unit_cost"] is None

    async def test_source_and_unit_cost_reach_the_insert(self) -> None:
        """A caller-supplied source/unit_cost must reach the ledger INSERT params
        unchanged (unit_cost is stringified for the DB param, as quantity is)."""
        from repositories.ledger_repo import record_transaction

        session = _make_session(balance=100.0)

        with patch("repositories.ledger_repo._update_running_balance", new=AsyncMock()), \
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
                source="OPENING_BALANCE",
                unit_cost=Decimal("3.25"),
            )

        ledger_call = session.execute.call_args_list[3]
        assert ledger_call.args[1]["source"] == "OPENING_BALANCE"
        assert ledger_call.args[1]["unit_cost"] == "3.25"


# ── Step 2b lot guard + LOT_OPENING tests ───────────────────────────────────

LOT_ID = "lot-001"


@pytest.mark.unit
class TestLotGuardAndLotOpening:

    async def test_batch_product_issue_without_lot_raises_lot_required(self) -> None:
        """A batch-tracked product's ISSUE with no lot_id must raise 422 LOT_REQUIRED."""
        from repositories.ledger_repo import record_transaction

        session = _make_session(balance=100.0, batch_tracking=True)

        with patch("repositories.ledger_repo._update_running_balance",
                   new=AsyncMock()) as mock_running, \
             patch("repositories.ledger_repo.write_to_outbox", new=AsyncMock()):
            with pytest.raises(HTTPException) as exc_info:
                await record_transaction(
                    session,
                    tenant_id=TENANT_ID,
                    transaction_type="ISSUE",
                    product_id=PRODUCT_ID,
                    warehouse_id=WAREHOUSE_ID,
                    quantity=Decimal("-10"),
                    performed_by=USER_ID,
                    idempotency_key=IDEM_KEY,
                )

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "LOT_REQUIRED"
        mock_running.assert_not_awaited()

    async def test_batch_product_issue_with_lot_drops_both_balances(self) -> None:
        """A batch-tracked product's ISSUE with lot_id must drop both the
        product total and the lot balance."""
        from repositories.ledger_repo import record_transaction

        session = _make_lot_session(balance=100.0, lot_balance=50.0, batch_tracking=True)

        with patch("repositories.ledger_repo._update_running_balance",
                   new=AsyncMock()) as mock_running, \
             patch("repositories.ledger_repo._update_lot_balance",
                   new=AsyncMock()) as mock_lot, \
             patch("repositories.ledger_repo.write_to_outbox", new=AsyncMock()):
            await record_transaction(
                session,
                tenant_id=TENANT_ID,
                transaction_type="ISSUE",
                product_id=PRODUCT_ID,
                warehouse_id=WAREHOUSE_ID,
                quantity=Decimal("-10"),
                performed_by=USER_ID,
                idempotency_key=IDEM_KEY,
                lot_id=LOT_ID,
            )

        mock_running.assert_awaited_once()
        assert mock_running.call_args.args[4] == Decimal("-10")
        mock_lot.assert_awaited_once()
        assert mock_lot.call_args.args[5] == Decimal("-10")

    async def test_batch_product_adjustment_and_transfer_out_without_lot_raise(self) -> None:
        """ADJUSTMENT and TRANSFER_OUT on a batch-tracked product both require
        a lot_id, same as ISSUE."""
        from repositories.ledger_repo import record_transaction

        for tx_type in ("ADJUSTMENT", "TRANSFER_OUT"):
            session = _make_session(balance=100.0, batch_tracking=True)
            with patch("repositories.ledger_repo._update_running_balance", new=AsyncMock()), \
                 patch("repositories.ledger_repo.write_to_outbox", new=AsyncMock()):
                with pytest.raises(HTTPException) as exc_info:
                    await record_transaction(
                        session,
                        tenant_id=TENANT_ID,
                        transaction_type=tx_type,
                        product_id=PRODUCT_ID,
                        warehouse_id=WAREHOUSE_ID,
                        quantity=Decimal("-5"),
                        performed_by=USER_ID,
                        idempotency_key=f"{IDEM_KEY}-{tx_type}",
                    )
            assert exc_info.value.status_code == 422
            assert exc_info.value.detail["code"] == "LOT_REQUIRED", (
                f"{tx_type} on a batch-tracked product must require a lot"
            )

    async def test_batch_product_reserve_without_lot_is_allowed(self) -> None:
        """RESERVE is balance-neutral, so it stays allowed without a lot even
        on a batch-tracked product."""
        from repositories.ledger_repo import record_transaction

        session = _make_session(balance=100.0, batch_tracking=True)

        with patch("repositories.ledger_repo._update_running_balance",
                   new=AsyncMock()) as mock_running, \
             patch("repositories.ledger_repo.write_to_outbox", new=AsyncMock()):
            await record_transaction(
                session,
                tenant_id=TENANT_ID,
                transaction_type="RESERVE",
                product_id=PRODUCT_ID,
                warehouse_id=WAREHOUSE_ID,
                quantity=Decimal("20"),
                performed_by=USER_ID,
                idempotency_key=IDEM_KEY,
            )

        mock_running.assert_not_awaited()

    async def test_non_batch_product_issue_without_lot_is_unchanged(self) -> None:
        """A non-batch product's ISSUE with no lot_id keeps working exactly as
        before lot support existed."""
        from repositories.ledger_repo import record_transaction

        session = _make_session(balance=100.0, batch_tracking=False)

        with patch("repositories.ledger_repo._update_running_balance",
                   new=AsyncMock()) as mock_running, \
             patch("repositories.ledger_repo.write_to_outbox", new=AsyncMock()):
            await record_transaction(
                session,
                tenant_id=TENANT_ID,
                transaction_type="ISSUE",
                product_id=PRODUCT_ID,
                warehouse_id=WAREHOUSE_ID,
                quantity=Decimal("-10"),
                performed_by=USER_ID,
                idempotency_key=IDEM_KEY,
            )

        mock_running.assert_awaited_once()

    async def test_non_batch_product_issue_with_lot_raises_lot_not_tracked(self) -> None:
        """A non-batch product's ISSUE with a lot_id must be rejected — defence
        in depth behind the receive API's own LOT_NOT_TRACKED check."""
        from repositories.ledger_repo import record_transaction

        session = _make_session(balance=100.0, batch_tracking=False)

        with patch("repositories.ledger_repo._update_running_balance",
                   new=AsyncMock()) as mock_running, \
             patch("repositories.ledger_repo.write_to_outbox", new=AsyncMock()):
            with pytest.raises(HTTPException) as exc_info:
                await record_transaction(
                    session,
                    tenant_id=TENANT_ID,
                    transaction_type="ISSUE",
                    product_id=PRODUCT_ID,
                    warehouse_id=WAREHOUSE_ID,
                    quantity=Decimal("-10"),
                    performed_by=USER_ID,
                    idempotency_key=IDEM_KEY,
                    lot_id=LOT_ID,
                )

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "LOT_NOT_TRACKED"
        mock_running.assert_not_awaited()

    async def test_lot_opening_without_lot_raises_lot_required(self) -> None:
        """LOT_OPENING always requires a lot_id, independent of batch_tracking."""
        from repositories.ledger_repo import record_transaction

        session = _make_session(balance=0.0)

        with patch("repositories.ledger_repo._update_running_balance",
                   new=AsyncMock()) as mock_running, \
             patch("repositories.ledger_repo._update_lot_balance",
                   new=AsyncMock()) as mock_lot, \
             patch("repositories.ledger_repo.write_to_outbox", new=AsyncMock()):
            with pytest.raises(HTTPException) as exc_info:
                await record_transaction(
                    session,
                    tenant_id=TENANT_ID,
                    transaction_type="LOT_OPENING",
                    product_id=PRODUCT_ID,
                    warehouse_id=WAREHOUSE_ID,
                    quantity=Decimal("30"),
                    performed_by=USER_ID,
                    idempotency_key=IDEM_KEY,
                )

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "LOT_REQUIRED"
        mock_running.assert_not_awaited()
        mock_lot.assert_not_awaited()

    async def test_lot_opening_with_lot_credits_lot_balance_only(self) -> None:
        """LOT_OPENING with a lot_id must credit lot_balances by the full
        quantity and write an immutable ledger row, while leaving
        inventory_balances (the product running total) untouched."""
        from repositories.ledger_repo import record_transaction

        # Custom session: idem INSERT, product balance SELECT (step 2),
        # lot balance SELECT FOR UPDATE (step 3b), ledger INSERT (step 4).
        # LOT_OPENING skips the Step 2b batch_tracking SELECT entirely (it is
        # in _LOT_ONLY_TYPES, checked before the batch_tracking branch).
        balance_row = MagicMock()
        balance_row.qty = 0.0
        balance_result = MagicMock()
        balance_result.fetchone.return_value = balance_row

        lot_balance_row = MagicMock()
        lot_balance_row.qty = 0.0
        lot_balance_result = MagicMock()
        lot_balance_result.fetchone.return_value = lot_balance_row

        idem_result = MagicMock()
        idem_result.rowcount = 1

        generic_result = MagicMock()
        generic_result.fetchone.return_value = None

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            idem_result, balance_result, lot_balance_result, generic_result,
        ])

        with patch("repositories.ledger_repo._update_running_balance",
                   new=AsyncMock()) as mock_running, \
             patch("repositories.ledger_repo._update_lot_balance",
                   new=AsyncMock()) as mock_lot, \
             patch("repositories.ledger_repo.write_to_outbox", new=AsyncMock()):
            await record_transaction(
                session,
                tenant_id=TENANT_ID,
                transaction_type="LOT_OPENING",
                product_id=PRODUCT_ID,
                warehouse_id=WAREHOUSE_ID,
                quantity=Decimal("30"),
                performed_by=USER_ID,
                idempotency_key=IDEM_KEY,
                lot_id=LOT_ID,
                lot_number="LOT-A1",
            )

        # inventory_balances (product total) must NOT be touched
        mock_running.assert_not_awaited()

        # lot_balances must be credited by the full quantity
        mock_lot.assert_awaited_once()
        assert mock_lot.call_args.args[2] == LOT_ID
        assert mock_lot.call_args.args[5] == Decimal("30")

        # the ledger row must still be written
        all_sql = [str(c.args[0]) for c in session.execute.call_args_list]
        assert any("INSERT INTO inventory_transactions" in sql for sql in all_sql)
        ledger_call = session.execute.call_args_list[3]
        assert ledger_call.args[1]["type"] == "LOT_OPENING"
        assert ledger_call.args[1]["lot_id"] == LOT_ID

    async def test_lot_totals_mismatch_clears_after_matching_lot_opening(self) -> None:
        """lot_totals_mismatch() must return None once SUM(lot_balances) equals
        the product's inventory_balances total — the state after a LOT_OPENING
        that matches the existing product total."""
        from repositories.lot_repo import lot_totals_mismatch

        inventory_row = MagicMock()
        inventory_row.qty = 30.0
        inventory_result = MagicMock()
        inventory_result.fetchone.return_value = inventory_row

        lot_sum_row = MagicMock()
        lot_sum_row.qty = 30.0
        lot_sum_result = MagicMock()
        lot_sum_result.fetchone.return_value = lot_sum_row

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[inventory_result, lot_sum_result])

        mismatch = await lot_totals_mismatch(
            session, TENANT_ID, PRODUCT_ID, WAREHOUSE_ID,
        )

        assert mismatch is None


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
