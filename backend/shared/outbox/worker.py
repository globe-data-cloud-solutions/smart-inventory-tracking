from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date
from typing import Awaitable, Callable, Coroutine, TypeVar

from celery import Celery
from celery.schedules import crontab
from sqlalchemy import text

from shared.db.session import AsyncSessionLocal
from shared.outbox.schemas import PAYLOAD_TYPES, ContractExpiryAlertPayload

logger = logging.getLogger(__name__)

T = TypeVar("T")

# One dedicated event loop per process, created lazily and reused across tasks —
# the asyncpg pool backing AsyncSessionLocal is bound to whichever loop first
# created it, so each call must run on the SAME loop (not a fresh one per call).
_loop: asyncio.AbstractEventLoop | None = None


def _run(coro: Coroutine[object, object, T]) -> T:
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
    return _loop.run_until_complete(coro)


app = Celery("smart", broker=os.environ["CELERY_BROKER_URL"])
app.conf.result_backend = os.environ["CELERY_RESULT_BACKEND"]

# Beat schedule — all times UTC
app.conf.beat_schedule = {
    "poll-pending-outbox": {
        "task": "shared.outbox.worker.poll_pending_outbox",
        "schedule": 30,  # every 30 seconds — outbox fallback
    },
    "check-contract-expiry": {
        "task": "shared.outbox.worker.check_contract_expiry",
        "schedule": crontab(hour=6, minute=0),  # daily at 06:00 UTC
    },
}
app.conf.timezone = "UTC"

OUTBOX_HANDLERS: dict[str, Callable[..., Awaitable[None]]] = {}


def register_handler(event_type: str) -> Callable:
    def decorator(func: Callable) -> Callable:
        OUTBOX_HANDLERS[event_type] = func
        return func
    return decorator


@register_handler("ContractExpiryAlert")
async def handle_contract_expiry_alert(
    payload: ContractExpiryAlertPayload, tenant_id: str
) -> None:
    """Log contract expiry alerts.

    Phase 3: wire to notification-service for email / push delivery.
    For now this handler acknowledges the event so it is not silently dropped
    and surfaces the alert in CloudWatch logs for SA monitoring.
    """
    days = payload.days_remaining
    if days is None or days < 0:
        log_level, label = logging.ERROR, "EXPIRED"
    elif days == 0:
        log_level, label = logging.ERROR, "EXPIRED TODAY"
    elif days <= 5:
        log_level, label = logging.WARNING, f"expires in {days} day(s)"
    else:
        log_level, label = logging.INFO, f"expires in {days} day(s)"

    logger.log(
        log_level,
        "ContractExpiryAlert: tenant_id=%s name=%s contract_end=%s status=%s",
        tenant_id,
        payload.tenant_name,
        payload.contract_end,
        label,
    )


@app.task(bind=True, max_retries=5, default_retry_delay=30)
def process_outbox_row(self, row_id: str) -> None:  # type: ignore[override]
    """Always check status before processing — tasks must be idempotent."""
    _run(_process(self, row_id))


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
            text(
                "UPDATE outbox SET status = 'PROCESSING', processing_started_at = now() "
                "WHERE id = :id"
            ),
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
                    "UPDATE outbox SET status = 'PROCESSED', processed_at = now(), "
                    "processing_started_at = NULL WHERE id = :id"
                ),
                {"id": row_id},
            )
            await session.commit()

    except Exception as exc:
        async with AsyncSessionLocal() as session:
            await session.execute(
                text(
                    "UPDATE outbox SET status = 'FAILED', attempts = attempts + 1, "
                    "last_error = :e, processing_started_at = NULL WHERE id = :id"
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
    _run(_poll())


async def _poll() -> None:
    # Step 1: recover rows stuck in PROCESSING (crashed worker recovery).
    # Rows in PROCESSING for > 10 minutes have no active worker — safe to reset.
    # Trade-off: a genuinely slow handler running near the 10-minute mark could race
    # with a newly dispatched task. FOR UPDATE SKIP LOCKED in _process ensures only
    # one worker wins the race; the other returns early safely.
    async with AsyncSessionLocal() as session:
        await session.execute(
            text(
                "UPDATE outbox SET status = 'PENDING', processing_started_at = NULL "
                "WHERE status = 'PROCESSING' "
                "AND processing_started_at < now() - interval '10 minutes'"
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


# Alert milestone days before expiry. Catch-up rule: if a run is missed and
# several milestones have elapsed, only the smallest un-notified milestone
# still >= days_left fires, and every larger milestone key is also marked
# notified so a missed day never double-fires once the gap is closed.
_EXPIRY_MILESTONES = [90, 30, 14, 5, 2, 1]


@app.task
def check_contract_expiry() -> None:
    """Daily beat task — alerts only; SA suspends manually (Alex 2026-10-07).

    For each tenant with a contract_end date:
      - If contract_end < today: fire a single "0d" ContractExpiryAlert
        (days_remaining = days_left, negative is OK) if not already notified.
        No status/is_active change is made — contract expiry is alerts-only.
      - Otherwise, catch-up milestone alerts: the smallest milestone in
        _EXPIRY_MILESTONES that is >= days_left and not yet notified fires once,
        marking that key and every larger milestone key as notified.
    """
    _run(_check_contracts())


async def _check_contracts() -> None:
    today = date.today()

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            text(
                "SELECT id, name, contract_end, status, contract_expiry_notified "
                "FROM tenants "
                "WHERE contract_end IS NOT NULL AND is_active = true "
                "AND coalesce(status, 'ACTIVE') NOT IN ('SUSPENDED', 'DEACTIVATED')"
            )
        )).fetchall()

    for row in rows:
        contract_end: date = row.contract_end
        if not contract_end:
            continue

        notified: list[str] = list(row.contract_expiry_notified or [])
        days_left: int = (contract_end - today).days
        tid = str(row.id)
        tname = str(row.name)

        # ── Expired: alerts only, no auto-suspend ────────────────────────────
        if days_left < 0:
            if "0d" in notified:
                continue
            async with AsyncSessionLocal() as session:
                await session.execute(
                    text(
                        "INSERT INTO outbox (tenant_id, event_type, payload, payload_ver) "
                        "VALUES (:tid, :etype, CAST(:payload AS jsonb), '1.0')"
                    ),
                    {
                        "tid":     tid,
                        "etype":   "ContractExpiryAlert",
                        "payload": json.dumps(ContractExpiryAlertPayload(
                            tenant_id=tid,
                            tenant_name=tname,
                            contract_end=contract_end.isoformat(),
                            days_remaining=days_left,
                        ).model_dump()),
                    },
                )
                await session.execute(
                    text(
                        "UPDATE tenants SET "
                        "contract_expiry_notified = contract_expiry_notified || CAST(:key AS jsonb) "
                        "WHERE id = :id"
                    ),
                    {"key": json.dumps("0d"), "id": tid},
                )
                await session.commit()
            logger.error(
                "ContractExpiryAlert fired: tenant=%s milestone=0d days_left=%d",
                tid, days_left,
            )
            continue

        # ── Pre-expiry milestone alerts, with catch-up for missed runs ───────
        candidates = [m for m in _EXPIRY_MILESTONES if m >= days_left and f"{m}d" not in notified]
        if not candidates:
            continue
        milestone = min(candidates)
        key = f"{milestone}d"
        marked_keys = [f"{m}d" for m in _EXPIRY_MILESTONES if m >= milestone and f"{m}d" not in notified]

        async with AsyncSessionLocal() as session:
            await session.execute(
                text(
                    "INSERT INTO outbox (tenant_id, event_type, payload, payload_ver) "
                    "VALUES (:tid, :etype, CAST(:payload AS jsonb), '1.0')"
                ),
                {
                    "tid":     tid,
                    "etype":   "ContractExpiryAlert",
                    "payload": json.dumps(ContractExpiryAlertPayload(
                        tenant_id=tid,
                        tenant_name=tname,
                        contract_end=contract_end.isoformat(),
                        days_remaining=days_left,
                    ).model_dump()),
                },
            )
            await session.execute(
                text(
                    "UPDATE tenants SET "
                    "contract_expiry_notified = contract_expiry_notified || CAST(:keys AS jsonb) "
                    "WHERE id = :id"
                ),
                {"keys": json.dumps(marked_keys), "id": tid},
            )
            await session.commit()
        logger.info(
            "ContractExpiryAlert fired: tenant=%s milestone=%s days_left=%d marked=%s",
            tid, key, days_left, marked_keys,
        )
