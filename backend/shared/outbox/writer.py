from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.outbox.schemas import BasePayload


async def write_to_outbox(
    session: AsyncSession,
    tenant_id: str,
    event_type: str,
    payload: BasePayload,
    idempotency_key: str | None = None,
) -> None:
    """Write an outbox row inside the SAME DB transaction as the primary record.

    Rules enforced here:
      - event_type must match payload.event_type (Literal field on each payload class).
        A mismatch means the caller passed the wrong payload type — caught at write time.
      - status is written explicitly as 'PENDING' so the intent is clear and readable
        without relying solely on the column default.
      - This function MUST NOT be called after session.commit(). Call it in the same
        async context block as the primary INSERT, before the session is committed.
      - The pg_notify trigger on the outbox table fires automatically after this INSERT
        to wake Celery workers immediately. No extra notify call is needed here.

    idempotency_key:
      Optional caller-supplied deduplication key.  When provided, the partial
      unique index on outbox(idempotency_key) prevents a second row with the same
      key from being inserted — the DB raises UniqueViolation which the application
      layer maps to HTTP 409.  Pass None (the default) when deduplication at the
      outbox level is not needed; multiple NULL-key rows are always permitted.
    """
    if event_type != payload.event_type:
        raise ValueError(
            f"event_type mismatch: caller passed {event_type!r} but "
            f"payload.event_type={payload.event_type!r}. Pass the correct payload type."
        )

    await session.execute(
        text(
            "INSERT INTO outbox "
            "(tenant_id, event_type, payload, payload_ver, status, idempotency_key) "
            "VALUES (:tid, :etype, :payload::jsonb, :ver, 'PENDING', :ikey)"
        ),
        {
            "tid":   tenant_id,
            "etype": payload.event_type,   # use payload's Literal field, not the raw string
            "payload": payload.model_dump_json(),
            "ver":   payload.version,
            "ikey":  idempotency_key,      # None → NULL in PostgreSQL
        },
    )
