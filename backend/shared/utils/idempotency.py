from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class DuplicateTransactionError(Exception):
    def __init__(self, idempotency_key: str) -> None:
        super().__init__(f"Duplicate transaction key: {idempotency_key}")
        self.idempotency_key = idempotency_key


async def check_and_register_idempotency_key(
    session: AsyncSession, tenant_id: str, idempotency_key: str, transaction_id: str
) -> None:
    """Raises DuplicateTransactionError (HTTP 409) if this tenant already used the key.

    Keys are scoped per tenant (migration 094): two tenants may use the same key.
    """
    result = await session.execute(
        text(
            "INSERT INTO inventory_transaction_keys (tenant_id, idempotency_key, transaction_id) "
            "VALUES (:tid, :key, :tx_id) ON CONFLICT (tenant_id, idempotency_key) DO NOTHING "
            "RETURNING transaction_id"
        ),
        {"tid": str(tenant_id), "key": idempotency_key, "tx_id": transaction_id},
    )
    if result.rowcount == 0:
        raise DuplicateTransactionError(idempotency_key)


async def idempotency_key_exists(session: AsyncSession, tenant_id: Optional[str], key: str) -> bool:
    """True if this tenant has already registered the key.

    With no tenant the answer is False without querying: an unscoped lookup
    would either leak other tenants' keys or, under RLS, match nothing.
    """
    if tenant_id is None:
        return False
    result = await session.execute(
        text(
            "SELECT 1 FROM inventory_transaction_keys "
            "WHERE tenant_id = :tid AND idempotency_key = :key"
        ),
        {"tid": str(tenant_id), "key": key},
    )
    return result.fetchone() is not None
