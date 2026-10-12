"""Lot repository — identity (stock_lots) and per-warehouse balances (lot_balances).

_update_lot_balance is the ONLY permitted writer to lot_balances, and it is
only ever called from record_transaction() in ledger_repo.py, in the same
transaction as the inventory_transactions INSERT — never after commit.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_or_create_lot(
    session: AsyncSession,
    tenant_id: str,
    product_id: str,
    lot_number: str,
    expiry_date: Optional[date],
    performed_by: str,
) -> str:
    """Return the id of the (tenant, product, lot_number) lot, creating it if new.

    Concurrency-safe: INSERT ... ON CONFLICT DO NOTHING followed by a SELECT,
    so two concurrent receipts for the same new lot never race.
    """
    stripped = (lot_number or "").strip()
    if not stripped:
        raise HTTPException(status_code=422, detail={"code": "LOT_NUMBER_REQUIRED"})

    await session.execute(
        text(
            "INSERT INTO stock_lots "
            "(tenant_id, product_id, lot_number, expiry_date, created_by) "
            "VALUES (:tid, :pid, :lot, :exp, :uid) "
            "ON CONFLICT (tenant_id, product_id, lot_number) DO NOTHING"
        ),
        {
            "tid": tenant_id,
            "pid": product_id,
            "lot": stripped,
            "exp": expiry_date,
            "uid": performed_by,
        },
    )

    result = await session.execute(
        text(
            "SELECT id, expiry_date FROM stock_lots "
            "WHERE tenant_id = :tid AND product_id = :pid AND lot_number = :lot"
        ),
        {"tid": tenant_id, "pid": product_id, "lot": stripped},
    )
    row = result.fetchone()

    existing_expiry = row.expiry_date
    if existing_expiry != expiry_date:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "LOT_EXPIRY_MISMATCH",
                "lot_number": stripped,
                "existing_expiry": existing_expiry.isoformat() if existing_expiry else None,
                "given_expiry": expiry_date.isoformat() if expiry_date else None,
            },
        )

    return str(row.id)


async def _get_lot_balance(
    session: AsyncSession,
    tenant_id: str,
    lot_id: str,
    warehouse_id: str,
    *,
    lock: bool = False,
) -> Decimal:
    sql = (
        "SELECT COALESCE(quantity, 0) AS qty FROM lot_balances "
        "WHERE tenant_id = :tid AND lot_id = :lid AND warehouse_id = :wid"
    )
    if lock:
        sql += " FOR UPDATE"
    result = await session.execute(
        text(sql),
        {"tid": tenant_id, "lid": lot_id, "wid": warehouse_id},
    )
    row = result.fetchone()
    return Decimal(str(row.qty)) if row else Decimal("0")


async def _update_lot_balance(
    session: AsyncSession,
    tenant_id: str,
    lot_id: str,
    product_id: str,
    warehouse_id: str,
    delta: Decimal,
) -> None:
    """Upsert lot_balances by delta.

    ONLY writer to lot_balances. Called only from record_transaction(), in the
    same DB transaction as the inventory_transactions INSERT.
    """
    await session.execute(
        text(
            "INSERT INTO lot_balances (tenant_id, lot_id, product_id, warehouse_id, quantity) "
            "VALUES (:tid, :lid, :pid, :wid, :qty) "
            "ON CONFLICT (tenant_id, lot_id, warehouse_id) "
            "DO UPDATE SET quantity   = lot_balances.quantity + EXCLUDED.quantity, "
            "             updated_at = now()"
        ),
        {
            "tid": tenant_id,
            "lid": lot_id,
            "pid": product_id,
            "wid": warehouse_id,
            "qty": str(delta),
        },
    )


async def lot_totals_mismatch(
    session: AsyncSession,
    tenant_id: str,
    product_id: str,
    warehouse_id: str,
) -> Optional[Decimal]:
    """Read-only diagnostic: inventory_balances total minus SUM(lot_balances) for
    this product/warehouse, when lots exist for it. Returns None when there are
    no lots (nothing to compare) or when the totals match exactly."""
    result = await session.execute(
        text(
            "SELECT COALESCE(quantity, 0) AS qty FROM inventory_balances "
            "WHERE tenant_id = :tid AND product_id = :pid AND warehouse_id = :wid "
            "AND lot_number IS NULL"
        ),
        {"tid": tenant_id, "pid": product_id, "wid": warehouse_id},
    )
    row = result.fetchone()
    inventory_total = Decimal(str(row.qty)) if row else Decimal("0")

    result = await session.execute(
        text(
            "SELECT COALESCE(SUM(quantity), 0) AS qty FROM lot_balances "
            "WHERE tenant_id = :tid AND product_id = :pid AND warehouse_id = :wid"
        ),
        {"tid": tenant_id, "pid": product_id, "wid": warehouse_id},
    )
    row = result.fetchone()
    lot_total = Decimal(str(row.qty)) if row else Decimal("0")

    if lot_total == Decimal("0"):
        return None

    mismatch = inventory_total - lot_total
    return None if mismatch == Decimal("0") else mismatch
