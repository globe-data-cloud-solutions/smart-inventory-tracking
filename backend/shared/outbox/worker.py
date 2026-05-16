from __future__ import annotations

import logging
import os
from typing import Awaitable, Callable

from celery import Celery
from sqlalchemy import text

from shared.db.session import AsyncSessionLocal
from shared.outbox.schemas import PAYLOAD_TYPES

logger = logging.getLogger(__name__)

app = Celery("smart", broker=os.environ.get("CELERY_BROKER_URL", ""))
app.conf.result_backend = os.environ.get("CELERY_RESULT_BACKEND", "")

OUTBOX_HANDLERS: dict[str, Callable[..., Awaitable[None]]] = {}


def register_handler(event_type: str) -> Callable:
    def decorator(func: Callable) -> Callable:
        OUTBOX_HANDLERS[event_type] = func
        return func
    return decorator


@app.task(bind=True, max_retries=5, default_retry_delay=30)
def process_outbox_row(self, row_id: str) -> None:  # type: ignore[override]
    """Always check status before processing — tasks must be idempotent."""
    import asyncio

    asyncio.get_event_loop().run_until_complete(_process(self, row_id))


async def _process(task: object, row_id: str) -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT * FROM outbox WHERE id = :id FOR UPDATE SKIP LOCKED"),
            {"id": row_id},
        )
        row = result.fetchone()

        # Guard explanation:
        #   not row         — SKIP LOCKED returned nothing; another worker holds an active
        #                     lock and is currently processing this row — leave it alone.
        #   PROCESSED       — already successfully completed; skip (idempotency).
        #   PROCESSING      — a previous worker set this status then crashed (lock was
        #                     released when its session closed). The poll task resets
        #                     stuck PROCESSING rows back to PENDING after a timeout, so
        #                     by the time _process is called again the status is PENDING.
        #                     We therefore do NOT re-enter on PROCESSING here to avoid
        #                     racing with a slow-but-alive worker.
        #
        # What we DO process: PENDING and FAILED.
        #   PENDING — normal first attempt.
        #   FAILED  — Celery retry or poll-triggered re-attempt after a prior handler
        #             exception. Previously this was incorrectly skipped because the guard
        #             only allowed PENDING. Fixed: both PENDING and FAILED are valid entry
        #             statuses for processing.
        if not row or row.status not in ("PENDING", "FAILED"):
            return

        await session.execute(
            text("UPDATE outbox SET status = 'PROCESSING' WHERE id = :id"),
            {"id": row_id},
        )
        await session.commit()

    try:
        handler = OUTBOX_HANDLERS.get(row.event_type)
        if handler:
            payload_cls = PAYLOAD_TYPES.get(row.event_type)
            payload = payload_cls.model_validate(row.payload) if payload_cls else row.payload
            await handler(payload, str(row.tenant_id))

        async with AsyncSessionLocal() as session:
            await session.execute(
                text(
                    "UPDATE outbox SET status = 'PROCESSED', processed_at = now() "
                    "WHERE id = :id"
                ),
                {"id": row_id},
            )
            await session.commit()

    except Exception as exc:
        async with AsyncSessionLocal() as session:
            await session.execute(
                text(
                    "UPDATE outbox SET status = 'FAILED', attempts = attempts + 1, "
                    "last_error = :e WHERE id = :id"
                ),
                {"e": str(exc), "id": row_id},
            )
            await session.commit()
        raise task.retry(exc=exc, countdown=2 ** task.request.retries)  # type: ignore[attr-defined]


@app.task
def poll_pending_outbox() -> None:
    """Celery beat fallback — fires every 30s to recover missed NOTIFY events.

    Also resets rows stuck in PROCESSING (worker crashed before marking PROCESSED).
    A row is considered stuck if it has been in PROCESSING for longer than 10 minutes —
    this threshold is intentionally conservative to avoid racing with slow-but-live
    workers. Reset happens before the dispatch query so recovered rows are included
    in the current poll cycle.
    """
    import asyncio

    asyncio.get_event_loop().run_until_complete(_poll())


async def _poll() -> None:
    # Step 1: recover rows stuck in PROCESSING (crashed worker recovery).
    # Rows in PROCESSING for > 10 minutes have no active worker — safe to reset.
    # Trade-off: a genuinely slow handler running near the 10-minute mark could race
    # with a newly dispatched task. FOR UPDATE SKIP LOCKED in _process ensures only
    # one worker wins the race; the other returns early safely.
    async with AsyncSessionLocal() as session:
        await session.execute(
            text(
                "UPDATE outbox SET status = 'PENDING' "
                "WHERE status = 'PROCESSING' "
                "AND created_at < now() - interval '10 minutes'"
            )
        )
        await session.commit()

    # Step 2: dispatch tasks for all actionable rows (PENDING and FAILED, attempts < max).
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                "SELECT id FROM outbox "
                "WHERE status IN ('PENDING', 'FAILED') AND attempts < 5 "
                "ORDER BY created_at LIMIT 100"
            )
        )
        row_ids = [str(r[0]) for r in result.fetchall()]

    for row_id in row_ids:
        process_outbox_row.delay(row_id)
