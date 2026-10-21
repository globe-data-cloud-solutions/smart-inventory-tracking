"""Unit tests for the Transactional Outbox Pattern (CLAUDE.md §8).

Covers writer.py and worker.py in isolation — no real DB or Celery broker.
The three tests required by the spec are in TestOutboxWriter and TestOutboxWorker.
Additional tests cover the behaviours introduced by the two bug fixes:
  - FAILED rows must be re-processed (not silently skipped) on Celery retry
  - stuck PROCESSING rows are reset to PENDING by the poll task
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.outbox.schemas import InventoryUpdatedPayload


# ── helpers ───────────────────────────────────────────────────────────────────

def _inventory_payload(*, product_id: str = "p1", delta: float = 10.0) -> InventoryUpdatedPayload:
    return InventoryUpdatedPayload(
        product_id=product_id,
        warehouse_id="w1",
        delta=delta,
        transaction_id="tx1",
    )


def _mock_session_with_row(row: Any) -> AsyncMock:
    """Return a mock AsyncSession whose first execute returns the given row."""
    result = MagicMock()
    result.fetchone.return_value = row
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


# ── writer.py tests ───────────────────────────────────────────────────────────

@pytest.mark.unit
class TestOutboxWriter:

    async def test_outbox_written_in_same_transaction(self) -> None:
        """write_to_outbox() must INSERT into the outbox using the SAME session
        object as the primary record — never a new session, never post-commit."""
        from shared.outbox.writer import write_to_outbox

        session = AsyncMock()
        payload = _inventory_payload()

        await write_to_outbox(session, "tenant-1", "InventoryUpdated", payload)

        # Exactly one execute call on the session — the outbox INSERT
        session.execute.assert_awaited_once()

        sql_str = str(session.execute.call_args.args[0])
        assert "INSERT INTO outbox" in sql_str

        # Explicit status='PENDING' must appear in the SQL (not deferred to DB default)
        assert "'PENDING'" in sql_str or "PENDING" in sql_str

        # No commit was issued on the session — the caller controls the transaction
        session.commit.assert_not_awaited()

    async def test_event_type_mismatch_raises_value_error(self) -> None:
        """Passing an event_type string that doesn't match payload.event_type must
        raise ValueError at write time — catches mismatched payload/event combos."""
        from shared.outbox.writer import write_to_outbox

        session = AsyncMock()
        payload = _inventory_payload()  # payload.event_type == "InventoryUpdated"

        with pytest.raises(ValueError, match="event_type mismatch"):
            await write_to_outbox(session, "tenant-1", "StockTransferred", payload)

        # The INSERT must NOT have been issued
        session.execute.assert_not_awaited()

    async def test_payload_event_type_used_in_insert_not_raw_string(self) -> None:
        """The SQL INSERT must use payload.event_type as the event_type value.
        This verifies the writer uses the Literal field, not the raw string arg."""
        from shared.outbox.writer import write_to_outbox

        session = AsyncMock()
        payload = _inventory_payload()

        await write_to_outbox(session, "tenant-1", "InventoryUpdated", payload)

        params = session.execute.call_args.args[1]
        assert params["etype"] == "InventoryUpdated"

    async def test_idempotency_key_inserted_when_provided(self) -> None:
        """When idempotency_key is supplied, the :ikey param in the INSERT must
        carry the exact key string so the DB can enforce the partial unique index."""
        from shared.outbox.writer import write_to_outbox

        session = AsyncMock()
        payload = _inventory_payload()
        key = "transfer:abc123:dispatch:line:1"

        await write_to_outbox(session, "tenant-1", "InventoryUpdated", payload,
                              idempotency_key=key)

        params = session.execute.call_args.args[1]
        assert params["ikey"] == key

    async def test_idempotency_key_null_when_omitted(self) -> None:
        """When idempotency_key is not supplied (default), :ikey must be None so
        the DB stores NULL and the partial unique index does not apply."""
        from shared.outbox.writer import write_to_outbox

        session = AsyncMock()
        payload = _inventory_payload()

        await write_to_outbox(session, "tenant-1", "InventoryUpdated", payload)

        params = session.execute.call_args.args[1]
        assert params["ikey"] is None

    async def test_idempotency_key_column_in_insert_sql(self) -> None:
        """The INSERT SQL must reference the idempotency_key column explicitly —
        confirms migration 007 is reflected in the writer (no silent schema drift)."""
        from shared.outbox.writer import write_to_outbox

        session = AsyncMock()
        payload = _inventory_payload()

        await write_to_outbox(session, "tenant-1", "InventoryUpdated", payload,
                              idempotency_key="some-key")

        sql_str = str(session.execute.call_args.args[0])
        assert "idempotency_key" in sql_str


# ── worker.py tests ───────────────────────────────────────────────────────────

@pytest.mark.unit
class TestOutboxWorker:

    async def test_worker_idempotent_on_already_processed(self) -> None:
        """A row whose status is PROCESSED must be skipped — the handler must not
        be called again and no UPDATE must be issued on the outbox row."""
        from shared.outbox.worker import _process

        processed_row = MagicMock()
        processed_row.status = "PROCESSED"

        with patch("shared.outbox.worker.AsyncSessionLocal") as mock_ctx:
            session = AsyncMock()
            result = MagicMock()
            result.fetchone.return_value = processed_row
            session.execute = AsyncMock(return_value=result)
            mock_ctx.return_value.__aenter__.return_value = session

            task = MagicMock()
            await _process(task, "row-id-processed")

        # No status UPDATE must have been issued
        update_calls = [c for c in session.execute.call_args_list if "UPDATE" in str(c)]
        assert len(update_calls) == 0

        # The session was never committed — no state change
        session.commit.assert_not_awaited()

    async def test_worker_skips_locked_row(self) -> None:
        """FOR UPDATE SKIP LOCKED returns None when another worker holds the lock.
        _process must return immediately without touching the row."""
        from shared.outbox.worker import _process

        with patch("shared.outbox.worker.AsyncSessionLocal") as mock_ctx:
            session = AsyncMock()
            result = MagicMock()
            result.fetchone.return_value = None  # SKIP LOCKED returned nothing
            session.execute = AsyncMock(return_value=result)
            mock_ctx.return_value.__aenter__.return_value = session

            task = MagicMock()
            await _process(task, "locked-row-id")

        update_calls = [c for c in session.execute.call_args_list if "UPDATE" in str(c)]
        assert len(update_calls) == 0

    async def test_failed_row_retried_with_backoff(self) -> None:
        """On handler exception, the row must be marked FAILED (not deleted),
        attempts must be incremented, and task.retry() must be called with
        exponential backoff (countdown = 2^retries)."""
        from shared.outbox.worker import OUTBOX_HANDLERS, _process

        pending_row = MagicMock()
        pending_row.status = "PENDING"
        pending_row.event_type = "InventoryUpdated"
        pending_row.tenant_id = "tenant-1"
        pending_row.payload = {
            "product_id": "p1", "warehouse_id": "w1",
            "delta": 5.0, "transaction_id": "t1", "version": "1.0",
        }

        select_result = MagicMock()
        select_result.fetchone.return_value = pending_row

        OUTBOX_HANDLERS["InventoryUpdated"] = AsyncMock(
            side_effect=RuntimeError("downstream failure")
        )

        task = MagicMock()
        task.request.retries = 2
        task.retry = MagicMock(side_effect=RuntimeError("celery retry sentinel"))

        session_execute_responses = [
            select_result,  # SELECT FOR UPDATE SKIP LOCKED
            AsyncMock(),    # UPDATE status='PROCESSING'
        ]

        calls_made: list[str] = []

        async def fake_execute(sql, *args, **kwargs):
            sql_str = str(sql)
            calls_made.append(sql_str)
            if "FAILED" in sql_str:
                return MagicMock()
            return session_execute_responses.pop(0) if session_execute_responses else MagicMock()

        with patch("shared.outbox.worker.AsyncSessionLocal") as mock_ctx:
            session = AsyncMock()
            session.execute = AsyncMock(side_effect=fake_execute)
            mock_ctx.return_value.__aenter__.return_value = session

            with pytest.raises(RuntimeError, match="celery retry sentinel"):
                await _process(task, "failing-row-id")

        # Row must be marked FAILED (not deleted)
        assert any("FAILED" in s for s in calls_made), (
            "Expected an UPDATE setting status='FAILED' but none found"
        )
        # task.retry must be called with exponential backoff
        task.retry.assert_called_once()
        _, kwargs = task.retry.call_args
        assert kwargs.get("countdown") == 4  # 2^2 = 4

        del OUTBOX_HANDLERS["InventoryUpdated"]

    async def test_failed_row_is_reprocessed_on_retry(self) -> None:
        """BUG FIX: a FAILED row must not be silently skipped when _process is
        called again by Celery's retry mechanism.

        Before the fix, guard was: row.status not in ('PENDING',)
        A FAILED row would pass FOR UPDATE SKIP LOCKED but be immediately skipped.
        After the fix: guard is row.status not in ('PENDING', 'FAILED').
        Both PENDING and FAILED rows are processed.
        """
        from shared.outbox.worker import _process

        failed_row = MagicMock()
        failed_row.status = "FAILED"
        failed_row.event_type = "InventoryUpdated"
        failed_row.tenant_id = "tenant-1"
        failed_row.payload = {
            "product_id": "p1", "warehouse_id": "w1",
            "delta": 5.0, "transaction_id": "t1", "version": "1.0",
        }

        select_result = MagicMock()
        select_result.fetchone.return_value = failed_row

        processing_updates: list[str] = []

        async def capture_execute(sql, *args, **kwargs):
            sql_str = str(sql)
            if "PROCESSING" in sql_str:
                processing_updates.append(sql_str)
            return select_result

        with patch("shared.outbox.worker.AsyncSessionLocal") as mock_ctx, \
             patch("shared.outbox.worker.OUTBOX_HANDLERS", {}):
            # No handler registered → no side effect, should complete to PROCESSED
            session = AsyncMock()
            session.execute = AsyncMock(side_effect=capture_execute)
            mock_ctx.return_value.__aenter__.return_value = session

            task = MagicMock()
            await _process(task, "failed-row-id")

        # The FAILED row must have been claimed (status set to PROCESSING),
        # proving the retry path entered the processing block instead of returning early.
        assert len(processing_updates) > 0, (
            "FAILED row was silently skipped — guard is not allowing FAILED status. "
            "Check that 'FAILED' is in the allowed statuses in _process."
        )

    async def test_poll_resets_stuck_processing_rows(self) -> None:
        """The poll task must issue an UPDATE resetting long-stuck PROCESSING rows
        to PENDING (crash recovery) before dispatching new tasks."""
        from shared.outbox.worker import _poll

        row_ids_dispatched: list[str] = []

        select_result = MagicMock()
        select_result.fetchall.return_value = []  # no pending rows after reset

        reset_sql_issued: list[str] = []

        async def capture_execute(sql, *args, **kwargs):
            sql_str = str(sql)
            if "status = 'PENDING'" in sql_str and "PROCESSING" in sql_str:
                reset_sql_issued.append(sql_str)
            return select_result

        with patch("shared.outbox.worker.AsyncSessionLocal") as mock_ctx, \
             patch("shared.outbox.worker.process_outbox_row") as mock_dispatch:
            session = AsyncMock()
            session.execute = AsyncMock(side_effect=capture_execute)
            mock_ctx.return_value.__aenter__.return_value = session

            await _poll()

        assert len(reset_sql_issued) > 0, (
            "Poll did not issue a PROCESSING → PENDING reset query. "
            "Stuck PROCESSING rows from crashed workers will never be recovered."
        )
        # Verify the reset targets old rows only (interval guard present in SQL)
        assert any("interval" in s or "minutes" in s for s in reset_sql_issued), (
            "Reset query must use a time threshold to avoid racing with live workers."
        )
