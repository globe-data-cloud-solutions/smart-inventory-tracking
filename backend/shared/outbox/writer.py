from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.outbox.schemas import BasePayload


async def write_to_outbox(
    session: AsyncSession,
    tenant_id: str,
    event_type: str,
    payload: BasePayload,
) -> None:
    """Must be called inside the same DB transaction as the primary record.
    Writing to the outbox AFTER the transaction commits breaks atomicity.
    The NOTIFY trigger fires automatically on INSERT — no extra code needed here.
    """
    await session.execute(
        text(
            "INSERT INTO outbox (tenant_id, event_type, payload, payload_ver) "
            "VALUES (:tid, :etype, :payload::jsonb, :ver)"
        ),
        {
            "tid": tenant_id,
            "etype": event_type,
            "payload": payload.model_dump_json(),
            "ver": payload.version,
        },
    )
