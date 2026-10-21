"""PostgreSQL LISTEN/NOTIFY integration for outbox worker wakeup.
Each outbox INSERT fires pg_notify('outbox_insert', row_id) via a DB trigger.
This module listens on that channel and dispatches Celery tasks immediately,
providing sub-second side-effect delivery without polling overhead.
"""

from __future__ import annotations

import asyncio
import logging
import os

import asyncpg

from shared.outbox.worker import process_outbox_row

logger = logging.getLogger(__name__)


async def listen_for_outbox_events() -> None:
    conn = await asyncpg.connect(
        os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    )

    async def on_notification(
        connection: asyncpg.Connection,
        pid: int,
        channel: str,
        payload: str,
    ) -> None:
        logger.debug("outbox NOTIFY received: row_id=%s", payload)
        process_outbox_row.delay(payload)

    await conn.add_listener("outbox_insert", on_notification)
    logger.info("Listening on outbox_insert channel")

    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await conn.remove_listener("outbox_insert", on_notification)
        await conn.close()


if __name__ == "__main__":
    asyncio.run(listen_for_outbox_events())
