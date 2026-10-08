## 8. Transactional Outbox Pattern

This replaces Apache Kafka. It provides equivalent async behaviour with zero new infrastructure.

### How it works

```
1. Service receives a request (e.g. receive stock)
2. In ONE database transaction:
   a. INSERT into inventory_transactions  (immutable ledger)
   b. INSERT into outbox                  (side-effect queue)
   Both succeed or both roll back — atomically.
3. PostgreSQL NOTIFY fires on outbox INSERT → Celery worker wakes immediately
   Celery beat polls every 30 seconds as fallback (missed NOTIFY recovery)
4. Celery worker reads PENDING outbox row:
   - Marks it PROCESSING (with SELECT FOR UPDATE SKIP LOCKED)
   - Executes side effect: send notification / trigger analytics ETL / update read model
   - Marks it PROCESSED
   - On failure: marks FAILED, increments attempts, Celery retries with backoff
```

### `write_to_outbox()` — call inside every state-changing transaction

```python
# backend/shared/outbox/writer.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

async def write_to_outbox(
    session: AsyncSession,
    tenant_id: str,
    event_type: str,
    payload: "BasePayload",
) -> None:
    """
    MUST be called inside the same DB transaction as the primary record.
    Writing to the outbox AFTER the transaction commits breaks atomicity.
    """
    await session.execute(
        text("INSERT INTO outbox (tenant_id, event_type, payload, payload_ver) "
             "VALUES (:tid, :etype, :payload::jsonb, :ver)"),
        {"tid": tenant_id, "etype": event_type,
         "payload": payload.model_dump_json(), "ver": payload.version}
    )
    # The NOTIFY trigger fires automatically on INSERT — no extra code needed here.
```

### Celery worker — idempotent handler

```python
# backend/shared/outbox/worker.py
from celery import Celery

app = Celery("smart", broker=settings.CELERY_BROKER_URL)

@app.task(bind=True, max_retries=5)
def process_outbox_row(self, row_id: str) -> None:
    """Always check status before processing — tasks must be idempotent."""
    async with AsyncSessionLocal() as session:
        row = await session.execute(
            text("SELECT * FROM outbox WHERE id=:id FOR UPDATE SKIP LOCKED"),
            {"id": row_id}
        )
        row = row.fetchone()
        if not row or row.status not in ("PENDING",):
            return  # already processed or locked by another worker

        await session.execute(
            text("UPDATE outbox SET status='PROCESSING' WHERE id=:id"), {"id": row_id})
        await session.commit()

    try:
        handler = OUTBOX_HANDLERS.get(row.event_type)
        if handler:
            await handler(row.payload, row.tenant_id)
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("UPDATE outbox SET status='PROCESSED',processed_at=now() WHERE id=:id"),
                {"id": row_id})
    except Exception as exc:
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("UPDATE outbox SET status='FAILED',attempts=attempts+1,last_error=:e WHERE id=:id"),
                {"e": str(exc), "id": row_id})
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)
```

### Supported event types

```python
# backend/shared/outbox/schemas.py
class InventoryUpdatedPayload(BasePayload):
    event_type: Literal["InventoryUpdated"] = "InventoryUpdated"
    product_id: str; warehouse_id: str; delta: float; transaction_id: str

class StockTransferredPayload(BasePayload):
    event_type: Literal["StockTransferred"] = "StockTransferred"
    from_warehouse_id: str; to_warehouse_id: str; product_id: str; quantity: float

class TenantOrgTypeChangedPayload(BasePayload):
    event_type: Literal["TenantOrgTypeChanged"] = "TenantOrgTypeChanged"
    from_type: str | None; to_type: str; changed_by: str

class FefoOverrideAppliedPayload(BasePayload):
    event_type: Literal["FefoOverrideApplied"] = "FefoOverrideApplied"
    override_log_id: str

# All event types: InventoryUpdated, StockTransferred, OrderCreated, ShipmentDispatched,
#                  AdjustmentApplied, StockCountCompleted, TenantOrgTypeChanged, FefoOverrideApplied
```

### Alerting thresholds

Set CloudWatch alarms when:
- Outbox PENDING row count > 500 (worker lag)
- Any row has `attempts >= 4` (approaching max retries)
- Any row has been PENDING for > 5 minutes

### Running the worker (2026-10-07)

Local dev — two commands, run from the repo root:

```bash
bash scripts/start_worker.sh
```

This loads `.env`, checks Redis is reachable, then starts (in the background,
logs under `logs/services/`):

```bash
celery -A shared.outbox.worker worker --pool=solo --loglevel=INFO   # celery_worker.log
celery -A shared.outbox.worker beat --loglevel=INFO                  # celery_beat.log
```

`--pool=solo` is a Windows/Git-Bash accommodation only. The `notify.py`
LISTEN/NOTIFY module exists but is **not** run locally — the beat-driven
30-second poll (`poll_pending_outbox`) is the only dispatch path in dev.

Future ECS deployment: two services, same image/env/secrets as
`notification-service`.

| Service | Command | Desired count |
|---|---|---|
| `outbox-worker` | `celery -A shared.outbox.worker worker --loglevel=INFO` (default prefork pool) | ≥ 1 |
| `outbox-beat` | `celery -A shared.outbox.worker beat --loglevel=INFO` | exactly 1 |

The `notify.py` listener is not deployed at launch — the beat poll is the
sole dispatch path in production too, for now.

**Contract expiry is alerts-only** (decided by Alex, 2026-10-07): the daily
`check_contract_expiry` task never suspends a tenant. An expired contract
(`contract_end < today`) fires exactly one `"0d"` `ContractExpiryAlert`
(negative `days_remaining` is expected) and stops there — the SA suspends
the tenant manually. For tenants not yet expired, pre-expiry milestones
(90/30/14/5/2/1 days) use a catch-up rule: if a beat run is missed and
several milestones have elapsed, only the smallest un-notified milestone
still `>= days_left` fires once, and every larger milestone key is marked
notified at the same time — so a missed day can never double-fire once the
gap closes.

**Known gap:** event handlers registered via `@register_handler` in each
service's `main.py` (e.g. inventory-service's handlers) are not imported by
the standalone `shared.outbox.worker` Celery process — only handlers defined
in `worker.py` itself (currently `ContractExpiryAlert`) actually run. Wiring
service-level handlers into the worker process is unresolved; events for
other types still reach `PROCESSED` (no handler = no-op), they just don't
trigger any side effect yet.

