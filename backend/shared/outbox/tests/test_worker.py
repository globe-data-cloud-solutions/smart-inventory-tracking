"""Unit tests for shared/outbox/worker.py (CLAUDE.md §8).

No real DB or Redis — AsyncSessionLocal is mocked throughout, matching the
style of backend/services/inventory-service/tests/unit/test_outbox.py.

Covers the 2026-10-07 worker fixes:
  - one event loop per process, reused across task invocations (py3.14-safe)
  - processing_started_at set on PROCESSING, cleared on PROCESSED/FAILED
  - the stuck-row poll reset uses processing_started_at, not created_at
  - contract expiry is alerts-only (no auto-suspend) with catch-up milestones
  - no `:param::jsonb` bind-then-cast syntax remains (asyncpg can't parse it)
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import shared.outbox.worker as worker


def test_worker_and_beat_init_call_safe_environment_guard() -> None:
    with patch("shared.outbox.worker.assert_safe_environment") as guard:
        worker._check_safe_environment()
    guard.assert_called_once_with()


@pytest.fixture(autouse=True)
def _reset_loop():
    """Each test gets a clean module-level loop so tests don't leak state."""
    worker._loop = None
    yield
    if worker._loop is not None and not worker._loop.is_closed():
        worker._loop.close()
    worker._loop = None


def _tenant_row(
    *,
    tid: str = "t1",
    name: str = "Acme",
    contract_end: date,
    status: str = "ACTIVE",
    notified: list[str] | None = None,
) -> Any:
    row = MagicMock()
    row.id = tid
    row.name = name
    row.contract_end = contract_end
    row.status = status
    row.contract_expiry_notified = notified or []
    return row


# ── _run: single reused loop ─────────────────────────────────────────────────

@pytest.mark.unit
class TestRun:

    async def _noop(self) -> int:
        return 1

    def test_reuses_same_loop_across_two_calls(self) -> None:
        async def coro() -> asyncio.AbstractEventLoop:
            return asyncio.get_event_loop()

        loop1 = worker._run(coro())
        loop2 = worker._run(coro())

        assert loop1 is loop2

    def test_new_event_loop_created_only_once(self) -> None:
        async def coro() -> int:
            return 1

        with patch("shared.outbox.worker.asyncio.new_event_loop", wraps=asyncio.new_event_loop) as spy:
            worker._run(coro())
            worker._run(coro())

        assert spy.call_count == 1


# ── _process: processing_started_at lifecycle ───────────────────────────────

@pytest.mark.unit
class TestProcessTimestamps:

    async def test_processing_sets_processing_started_at(self) -> None:
        pending_row = MagicMock()
        pending_row.status = "PENDING"
        pending_row.event_type = "unregistered_event"
        pending_row.tenant_id = "tenant-1"
        pending_row.payload = {}

        select_result = MagicMock()
        select_result.fetchone.return_value = pending_row

        calls: list[str] = []

        async def capture_execute(sql, *args, **kwargs):
            calls.append(str(sql))
            return select_result

        with patch("shared.outbox.worker.AsyncSessionLocal") as mock_ctx, \
             patch("shared.outbox.worker.OUTBOX_HANDLERS", {}):
            session = AsyncMock()
            session.execute = AsyncMock(side_effect=capture_execute)
            mock_ctx.return_value.__aenter__.return_value = session

            task = MagicMock()
            await worker._process(task, "row-id")

        processing_calls = [c for c in calls if "PROCESSING" in c]
        assert len(processing_calls) == 1
        assert "processing_started_at = now()" in processing_calls[0]

    async def test_processed_clears_processing_started_at(self) -> None:
        pending_row = MagicMock()
        pending_row.status = "PENDING"
        pending_row.event_type = "unregistered_event"
        pending_row.tenant_id = "tenant-1"
        pending_row.payload = {}

        select_result = MagicMock()
        select_result.fetchone.return_value = pending_row

        calls: list[str] = []

        async def capture_execute(sql, *args, **kwargs):
            calls.append(str(sql))
            return select_result

        with patch("shared.outbox.worker.AsyncSessionLocal") as mock_ctx, \
             patch("shared.outbox.worker.OUTBOX_HANDLERS", {}):
            session = AsyncMock()
            session.execute = AsyncMock(side_effect=capture_execute)
            mock_ctx.return_value.__aenter__.return_value = session

            task = MagicMock()
            await worker._process(task, "row-id")

        processed_calls = [c for c in calls if "PROCESSED" in c]
        assert len(processed_calls) == 1
        assert "processing_started_at = NULL" in processed_calls[0]

    async def test_handlerless_event_still_reaches_processed(self) -> None:
        pending_row = MagicMock()
        pending_row.status = "PENDING"
        pending_row.event_type = "SomeUnregisteredType"
        pending_row.tenant_id = "tenant-1"
        pending_row.payload = {}

        select_result = MagicMock()
        select_result.fetchone.return_value = pending_row

        calls: list[str] = []

        async def capture_execute(sql, *args, **kwargs):
            calls.append(str(sql))
            return select_result

        with patch("shared.outbox.worker.AsyncSessionLocal") as mock_ctx, \
             patch("shared.outbox.worker.OUTBOX_HANDLERS", {}):
            session = AsyncMock()
            session.execute = AsyncMock(side_effect=capture_execute)
            mock_ctx.return_value.__aenter__.return_value = session

            task = MagicMock()
            await worker._process(task, "row-id")

        assert any("PROCESSED" in c for c in calls)
        assert not any("FAILED" in c for c in calls)

    async def test_failed_clears_processing_started_at(self) -> None:
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

        calls: list[str] = []

        async def capture_execute(sql, *args, **kwargs):
            sql_str = str(sql)
            calls.append(sql_str)
            return select_result

        task = MagicMock()
        task.request.retries = 0
        task.retry = MagicMock(side_effect=RuntimeError("retry sentinel"))

        with patch("shared.outbox.worker.AsyncSessionLocal") as mock_ctx, \
             patch.dict(worker.OUTBOX_HANDLERS, {
                 "InventoryUpdated": AsyncMock(side_effect=RuntimeError("boom"))
             }):
            session = AsyncMock()
            session.execute = AsyncMock(side_effect=capture_execute)
            mock_ctx.return_value.__aenter__.return_value = session

            with pytest.raises(RuntimeError, match="retry sentinel"):
                await worker._process(task, "row-id")

        failed_calls = [c for c in calls if "FAILED" in c]
        assert len(failed_calls) == 1
        assert "processing_started_at = NULL" in failed_calls[0]


# ── _poll: stuck-row reset uses processing_started_at ────────────────────────

@pytest.mark.unit
class TestPollResetColumn:

    async def test_reset_sql_uses_processing_started_at_not_created_at(self) -> None:
        select_result = MagicMock()
        select_result.fetchall.return_value = []

        reset_sql: list[str] = []

        async def capture_execute(sql, *args, **kwargs):
            sql_str = str(sql)
            if "status = 'PENDING'" in sql_str:
                reset_sql.append(sql_str)
            return select_result

        with patch("shared.outbox.worker.AsyncSessionLocal") as mock_ctx, \
             patch("shared.outbox.worker.process_outbox_row"):
            session = AsyncMock()
            session.execute = AsyncMock(side_effect=capture_execute)
            mock_ctx.return_value.__aenter__.return_value = session

            await worker._poll()

        assert len(reset_sql) == 1
        assert "processing_started_at" in reset_sql[0]
        assert "created_at" not in reset_sql[0]


# ── _check_contracts: alerts-only + catch-up milestones ─────────────────────

@pytest.mark.unit
class TestContractExpiry:

    async def test_expired_fires_one_0d_alert_no_suspend(self) -> None:
        today = date.today()
        row = _tenant_row(contract_end=today - timedelta(days=3), notified=[])

        select_result = MagicMock()
        select_result.fetchall.return_value = [row]

        insert_calls: list[tuple[str, dict]] = []
        update_calls: list[tuple[str, dict]] = []

        async def capture_execute(sql, params=None, *args, **kwargs):
            sql_str = str(sql)
            if sql_str.strip().upper().startswith("SELECT"):
                return select_result
            if "INSERT INTO outbox" in sql_str:
                insert_calls.append((sql_str, params or {}))
            elif "UPDATE tenants" in sql_str:
                update_calls.append((sql_str, params or {}))
            return MagicMock()

        with patch("shared.outbox.worker.AsyncSessionLocal") as mock_ctx:
            session = AsyncMock()
            session.execute = AsyncMock(side_effect=capture_execute)
            mock_ctx.return_value.__aenter__.return_value = session

            await worker._check_contracts()

        assert len(insert_calls) == 1
        payload = json.loads(insert_calls[0][1]["payload"])
        assert payload["days_remaining"] == -3

        assert len(update_calls) == 1
        assert "contract_expiry_notified" in update_calls[0][0]
        assert "status" not in update_calls[0][0]
        assert "is_active" not in update_calls[0][0]

    async def test_expired_already_notified_fires_nothing(self) -> None:
        today = date.today()
        row = _tenant_row(contract_end=today - timedelta(days=3), notified=["0d"])

        select_result = MagicMock()
        select_result.fetchall.return_value = [row]

        calls: list[str] = []

        async def capture_execute(sql, params=None, *args, **kwargs):
            sql_str = str(sql)
            if sql_str.strip().upper().startswith("SELECT"):
                return select_result
            calls.append(sql_str)
            return MagicMock()

        with patch("shared.outbox.worker.AsyncSessionLocal") as mock_ctx:
            session = AsyncMock()
            session.execute = AsyncMock(side_effect=capture_execute)
            mock_ctx.return_value.__aenter__.return_value = session

            await worker._check_contracts()

        assert calls == []

    async def test_catch_up_20_days_nothing_notified_marks_30_and_90(self) -> None:
        today = date.today()
        row = _tenant_row(contract_end=today + timedelta(days=20), notified=[])

        select_result = MagicMock()
        select_result.fetchall.return_value = [row]

        insert_calls: list[dict] = []
        update_calls: list[dict] = []

        async def capture_execute(sql, params=None, *args, **kwargs):
            sql_str = str(sql)
            if sql_str.strip().upper().startswith("SELECT"):
                return select_result
            if "INSERT INTO outbox" in sql_str:
                insert_calls.append(params or {})
            elif "UPDATE tenants" in sql_str:
                update_calls.append(params or {})
            return MagicMock()

        with patch("shared.outbox.worker.AsyncSessionLocal") as mock_ctx:
            session = AsyncMock()
            session.execute = AsyncMock(side_effect=capture_execute)
            mock_ctx.return_value.__aenter__.return_value = session

            await worker._check_contracts()

        assert len(insert_calls) == 1
        payload = json.loads(insert_calls[0]["payload"])
        assert payload["days_remaining"] == 20

        assert len(update_calls) == 1
        marked = json.loads(update_calls[0]["keys"])
        assert sorted(marked) == sorted(["90d", "30d"])

    async def test_exact_day_14_with_90_30_notified_fires_14_only(self) -> None:
        today = date.today()
        row = _tenant_row(
            contract_end=today + timedelta(days=14),
            notified=["90d", "30d"],
        )

        select_result = MagicMock()
        select_result.fetchall.return_value = [row]

        insert_calls: list[dict] = []
        update_calls: list[dict] = []

        async def capture_execute(sql, params=None, *args, **kwargs):
            sql_str = str(sql)
            if sql_str.strip().upper().startswith("SELECT"):
                return select_result
            if "INSERT INTO outbox" in sql_str:
                insert_calls.append(params or {})
            elif "UPDATE tenants" in sql_str:
                update_calls.append(params or {})
            return MagicMock()

        with patch("shared.outbox.worker.AsyncSessionLocal") as mock_ctx:
            session = AsyncMock()
            session.execute = AsyncMock(side_effect=capture_execute)
            mock_ctx.return_value.__aenter__.return_value = session

            await worker._check_contracts()

        assert len(insert_calls) == 1
        payload = json.loads(insert_calls[0]["payload"])
        assert payload["days_remaining"] == 14

        assert len(update_calls) == 1
        marked = json.loads(update_calls[0]["keys"])
        assert marked == ["14d"]

    async def test_already_notified_milestone_fires_nothing(self) -> None:
        today = date.today()
        row = _tenant_row(
            contract_end=today + timedelta(days=30),
            notified=["90d", "30d"],
        )

        select_result = MagicMock()
        select_result.fetchall.return_value = [row]

        calls: list[str] = []

        async def capture_execute(sql, params=None, *args, **kwargs):
            sql_str = str(sql)
            if sql_str.strip().upper().startswith("SELECT"):
                return select_result
            calls.append(sql_str)
            return MagicMock()

        with patch("shared.outbox.worker.AsyncSessionLocal") as mock_ctx:
            session = AsyncMock()
            session.execute = AsyncMock(side_effect=capture_execute)
            mock_ctx.return_value.__aenter__.return_value = session

            await worker._check_contracts()

        assert calls == []


# ── _ensure_future_partitions: idempotent monthly partition maintenance ─────

@pytest.mark.unit
class TestEnsureFuturePartitions:

    @staticmethod
    def _mock_session(existing_names: set[str], creates: list[str]) -> AsyncMock:
        async def capture_execute(sql, params=None, *args, **kwargs):
            sql_str = str(sql)
            if "to_regclass" in sql_str:
                result = MagicMock()
                result.scalar.return_value = (params or {}).get("name") in existing_names
                return result
            if "CREATE TABLE IF NOT EXISTS" in sql_str:
                name = sql_str.split("CREATE TABLE IF NOT EXISTS ")[1].split(" ")[0]
                creates.append(name)
                existing_names.add(name)
            return MagicMock()

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=capture_execute)
        return session

    async def test_idempotent_second_run_creates_nothing(self) -> None:
        existing: set[str] = set()
        creates: list[str] = []

        with patch("shared.outbox.worker.AsyncSessionLocal") as mock_ctx:
            session = self._mock_session(existing, creates)
            mock_ctx.return_value.__aenter__.return_value = session
            await worker._ensure_future_partitions()

        # current month + PARTITION_FUTURE_MONTHS future months = 4 total
        assert len(creates) == worker.PARTITION_FUTURE_MONTHS + 1

        creates.clear()
        with patch("shared.outbox.worker.AsyncSessionLocal") as mock_ctx:
            session = self._mock_session(existing, creates)
            mock_ctx.return_value.__aenter__.return_value = session
            await worker._ensure_future_partitions()

        assert creates == [], "second run must be a no-op — partitions already exist"

    async def test_creates_exactly_the_missing_months(self) -> None:
        today = date.today()
        month0 = worker._partition_name(today.year, today.month)

        # Only the current month's partition pre-exists; the remaining
        # PARTITION_FUTURE_MONTHS future months are missing.
        existing: set[str] = {month0}
        creates: list[str] = []

        with patch("shared.outbox.worker.AsyncSessionLocal") as mock_ctx:
            session = self._mock_session(existing, creates)
            mock_ctx.return_value.__aenter__.return_value = session
            await worker._ensure_future_partitions()

        assert month0 not in creates
        assert len(creates) == worker.PARTITION_FUTURE_MONTHS
        assert len(set(creates)) == len(creates), "no duplicate partitions created"

    async def test_new_partition_gets_tenant_rls(self) -> None:
        """Migration 091 (D9): a new partition gets RLS + tenant_isolation in the
        same session as its CREATE TABLE, run under the system context."""
        existing: set[str] = set()
        creates: list[str] = []

        with patch("shared.outbox.worker.AsyncSessionLocal") as mock_ctx:
            session = self._mock_session(existing, creates)
            mock_ctx.return_value.__aenter__.return_value = session
            await worker._ensure_future_partitions()

        statements = [" ".join(str(c.args[0]).split()) for c in session.execute.await_args_list]
        assert "set_config('app.is_sa', :sa, true)" in statements[0]
        for name in creates:
            assert f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY" in statements
            policy = [s for s in statements if s.startswith(f"CREATE POLICY tenant_isolation ON {name} ")]
            assert len(policy) == 1
            assert "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid" in policy[0]
            assert "COALESCE(current_setting('app.is_sa', true), '') = 'on'" in policy[0]
            assert "WITH CHECK" in policy[0]


# ── _run_initial_partition_check: beat_init startup hook ────────────────────

@pytest.mark.unit
class TestRunInitialPartitionCheck:

    def test_fresh_db_creates_exactly_four_then_is_idempotent(self) -> None:
        # Plain (non-async) test: _run_initial_partition_check is a sync Celery
        # signal handler that manages its own event loop via _run() — calling
        # it from inside pytest-asyncio's own running loop would raise
        # "Cannot run the event loop while another loop is running".
        existing: set[str] = set()
        creates: list[str] = []

        with patch("shared.outbox.worker.AsyncSessionLocal") as mock_ctx:
            session = TestEnsureFuturePartitions._mock_session(existing, creates)
            mock_ctx.return_value.__aenter__.return_value = session
            worker._run_initial_partition_check()

        assert len(creates) == 4  # current month + 3 future

        creates.clear()
        with patch("shared.outbox.worker.AsyncSessionLocal") as mock_ctx:
            session = TestEnsureFuturePartitions._mock_session(existing, creates)
            mock_ctx.return_value.__aenter__.return_value = session
            worker._run_initial_partition_check()

        assert creates == [], "re-running the startup check must be a no-op"

    def test_errors_are_logged_not_raised(self, caplog: pytest.LogCaptureFixture) -> None:
        async def _boom() -> None:
            raise RuntimeError("db unavailable")

        # Patch _ensure_future_partitions itself (not _run) so no real coroutine
        # object is ever left unawaited — _run still genuinely executes _boom().
        with patch("shared.outbox.worker._ensure_future_partitions", _boom), \
             caplog.at_level(logging.ERROR):
            worker._run_initial_partition_check()  # must not raise

        assert "Startup partition check failed" in caplog.text


# ── static source check: no bind-param-then-cast syntax remains ─────────────

@pytest.mark.unit
class TestNoBindParamCast:

    def test_no_param_colon_colon_jsonb_in_worker_source(self) -> None:
        src = Path(worker.__file__).read_text(encoding="utf-8")
        import re
        matches = re.findall(r":\w+::", src)
        assert matches == [], f"found bind-param-then-cast syntax: {matches}"
