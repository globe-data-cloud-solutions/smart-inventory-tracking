from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models.inventory import InventoryTransactionKey


class DuplicateTransactionError(Exception):
    def __init__(self, idempotency_key: str) -> None:
        super().__init__(f"Duplicate transaction key: {idempotency_key}")
        self.idempotency_key = idempotency_key


async def check_and_register_idempotency_key(
    session: AsyncSession, idempotency_key: str, transaction_id: str
) -> None:
    """Raises DuplicateTransactionError (HTTP 409) if key already exists."""
    result = await session.execute(
        text(
            "INSERT INTO inventory_transaction_keys (idempotency_key, transaction_id) "
            "VALUES (:key, :tx_id) ON CONFLICT (idempotency_key) DO NOTHING "
            "RETURNING transaction_id"
        ),
        {"key": idempotency_key, "tx_id": transaction_id},
    )
    if result.rowcount == 0:
        raise DuplicateTransactionError(idempotency_key)


async def idempotency_key_exists(session: AsyncSession, key: str) -> bool:
    result = await session.execute(
        text("SELECT 1 FROM inventory_transaction_keys WHERE idempotency_key = :key"),
        {"key": key},
    )
    return result.fetchone() is not None
