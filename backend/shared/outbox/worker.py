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
        if not row or row.status not in ("PENDING",):
            return  # already processed or locked by another worker

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
                    "UPDATE outbox SET status = 'PROCESSED', processed_at = now() WHERE id = :id"
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
    """Celery beat fallback — fires every 30s to recover missed NOTIFY events."""
    import asyncio

    asyncio.get_event_loop().run_until_complete(_poll())


async def _poll() -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                "SELECT id FROM outbox WHERE status IN ('PENDING', 'FAILED') "
                "AND attempts < 5 ORDER BY created_at LIMIT 100"
            )
        )
        row_ids = [str(r[0]) for r in result.fetchall()]

    for row_id in row_ids:
        process_outbox_row.delay(row_id)
