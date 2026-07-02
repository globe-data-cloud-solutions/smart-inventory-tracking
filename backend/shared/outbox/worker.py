from __future__ import annotations

import json
import logging
import os
from datetime import date, timedelta
from typing import Awaitable, Callable

from celery import Celery
from celery.schedules import crontab
from sqlalchemy import text

from shared.db.session import AsyncSessionLocal
from shared.outbox.schemas import PAYLOAD_TYPES, ContractExpiryAlertPayload

logger = logging.getLogger(__name__)

app = Celery("smart", broker=os.environ.get("CELERY_BROKER_URL", ""))
app.conf.result_backend = os.environ.get("CELERY_RESULT_BACKEND", "")

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


# Alert milestone days before expiry. "0" means expired (auto-suspend).
_EXPIRY_MILESTONES = [90, 30, 14, 5, 2, 1]


@app.task
def check_contract_expiry() -> None:
    """Daily beat task — auto-suspends expired tenants and fires pre-expiry alerts.

    For each tenant with a contract_end date:
      - If contract_end < today AND status is not SUSPENDED/DEACTIVATED → suspend.
      - For each milestone in _EXPIRY_MILESTONES where (contract_end - today) == days:
        fire a ContractExpiryAlert outbox event if the milestone has not been
        notified yet (tracked in contract_expiry_notified JSONB column).
    """
    import asyncio

    asyncio.get_event_loop().run_until_complete(_check_contracts())


async def _check_contracts() -> None:
    today = date.today()

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            text(
                "SELECT id, name, contract_end, status, contract_expiry_notified "
                "FROM tenants "
                "WHERE contract_end IS NOT NULL AND is_active = true OR status = 'ACTIVE'"
            )
        )).fetchall()

    for row in rows:
        contract_end: date = row.contract_end
        if not contract_end:
            continue

        notified: list[str] = list(row.contract_expiry_notified or [])
        days_left: int = (contract_end - today).days
        status: str = str(row.status) if row.status else "ACTIVE"
        tid = str(row.id)
        tname = str(row.name)

        # ── Auto-suspend if contract expired ─────────────────────────────────
        if days_left < 0 and status not in ("SUSPENDED", "DEACTIVATED"):
            async with AsyncSessionLocal() as session:
                await session.execute(
                    text(
                        "UPDATE tenants SET status = 'SUSPENDED', is_active = false, "
                        "updated_at = now() WHERE id = :id"
                    ),
                    {"id": tid},
                )
                await session.execute(
                    text(
                        "INSERT INTO tenant_activity_log "
                        "(tenant_id, actor_id, actor_email, action, old_value, new_value, note) "
                        "VALUES (:tid, :aid, :ae, :action, :old, :new, :note)"
                    ),
                    {
                        "tid":    tid,
                        "aid":    "00000000-0000-0000-0000-000000000000",  # system actor
                        "ae":     "system@smart-platform",
                        "action": "AUTO_SUSPEND_EXPIRED",
                        "old":    status,
                        "new":    "SUSPENDED",
                        "note":   f"Contract ended {contract_end.isoformat()}. Auto-suspended by system.",
                    },
                )
                # Write outbox alert (days_remaining=0 means expired)
                if "0d" not in notified:
                    await session.execute(
                        text(
                            "INSERT INTO outbox (tenant_id, event_type, payload, payload_ver) "
                            "VALUES (:tid, :etype, :payload::jsonb, '1.0')"
                        ),
                        {
                            "tid":     tid,
                            "etype":   "ContractExpiryAlert",
                            "payload": json.dumps(ContractExpiryAlertPayload(
                                tenant_id=tid,
                                tenant_name=tname,
                                contract_end=contract_end.isoformat(),
                                days_remaining=0,
                            ).model_dump()),
                        },
                    )
                    await session.execute(
                        text(
                            "UPDATE tenants SET "
                            "contract_expiry_notified = contract_expiry_notified || '\"0d\"'::jsonb "
                            "WHERE id = :id"
                        ),
                        {"id": tid},
                    )
                await session.commit()
            continue  # no milestone alerts for an already-expired tenant

        # ── Pre-expiry milestone alerts ───────────────────────────────────────
        for milestone in _EXPIRY_MILESTONES:
            key = f"{milestone}d"
            if days_left == milestone and key not in notified:
                async with AsyncSessionLocal() as session:
                    await session.execute(
                        text(
                            "INSERT INTO outbox (tenant_id, event_type, payload, payload_ver) "
                            "VALUES (:tid, :etype, :payload::jsonb, '1.0')"
                        ),
                        {
                            "tid":     tid,
                            "etype":   "ContractExpiryAlert",
                            "payload": json.dumps(ContractExpiryAlertPayload(
                                tenant_id=tid,
                                tenant_name=tname,
                                contract_end=contract_end.isoformat(),
                                days_remaining=milestone,
                            ).model_dump()),
                        },
                    )
                    await session.execute(
                        text(
                            "UPDATE tenants SET "
                            "contract_expiry_notified = contract_expiry_notified || :key::jsonb "
                            "WHERE id = :id"
                        ),
                        {"key": json.dumps(key), "id": tid},
                    )
                    await session.commit()
                logger.info(
                    "ContractExpiryAlert fired: tenant=%s milestone=%s days_left=%d",
                    tid, key, days_left,
                )
