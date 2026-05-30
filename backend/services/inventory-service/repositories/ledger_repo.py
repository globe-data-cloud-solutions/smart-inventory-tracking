"""Inventory ledger repository — the ONLY permitted writer to inventory_balances.

All stock mutations MUST flow through record_transaction(). No other code path
may issue a direct INSERT/UPDATE to inventory_balances.

Enforcement chain (CLAUDE.md §14, Business Rules #2, #26):
  1. Application rule: only record_transaction() may call _update_running_balance()
  2. Database rule:    PostgreSQL RULE on warehouse_stock/inventory_balances rejects
                       direct writes outside the privileged ledger session role
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.outbox.schemas import InventoryUpdatedPayload
from shared.outbox.writer import write_to_outbox
from shared.utils.idempotency import DuplicateTransactionError, check_and_register_idempotency_key


async def _get_balance(
    session: AsyncSession,
    tenant_id: str,
    product_id: str,
    warehouse_id: str,
    *,
    lock: bool = False,
) -> Decimal:
    """Read current balance from inventory_balances, optionally acquiring a row lock."""
    sql = (
        "SELECT COALESCE(quantity, 0) AS qty FROM inventory_balances "
        "WHERE tenant_id = :tid AND product_id = :pid AND warehouse_id = :wid "
        "AND lot_number IS NULL"
    )
    if lock:
        sql += " FOR UPDATE"
    result = await session.execute(
        text(sql),
        {"tid": tenant_id, "pid": product_id, "wid": warehouse_id},
    )
    row = result.fetchone()
    return Decimal(str(row.qty)) if row else Decimal("0")


async def _update_running_balance(
    session: AsyncSession,
    tenant_id: str,
    product_id: str,
    warehouse_id: str,
    delta: Decimal,
) -> None:
    """Upsert inventory_balances by delta.

    This is the ONLY function permitted to write to inventory_balances.
    Must always be called inside the same DB transaction as the
    inventory_transactions INSERT — never after commit.
    """
    await session.execute(
        text(
            "INSERT INTO inventory_balances (tenant_id, product_id, warehouse_id, quantity) "
            "VALUES (:tid, :pid, :wid, :qty) "
            "ON CONFLICT (tenant_id, product_id, warehouse_id) WHERE lot_number IS NULL "
            "DO UPDATE SET quantity   = inventory_balances.quantity + EXCLUDED.quantity, "
            "             updated_at = now()"
        ),
        {
            "tid": tenant_id,
            "pid": product_id,
            "wid": warehouse_id,
            "qty": str(delta),
        },
    )


async def record_transaction(
    session: AsyncSession,
    tenant_id: str,
    transaction_type: str,
    product_id: str,
    warehouse_id: str,
    quantity: Decimal,
    performed_by: str,
    idempotency_key: str,
    *,
    reference_type: Optional[str] = None,
    reference_id: Optional[str] = None,
    lot_id: Optional[str] = None,
    notes: Optional[str] = None,
) -> str:
    """Record an immutable ledger entry and conditionally update the running balance.

    Single entry point for all inventory mutations. Sequence within ONE transaction:
      1. Idempotency guard  — HTTP 409 on duplicate key
      2. Pessimistic lock   — FOR UPDATE on balance row prevents concurrent races
      3. Stock floor check  — HTTP 422 when balance + quantity would go negative
                             SKIPPED for _BALANCE_NEUTRAL_TYPES (audit-only entries)
      4. Ledger INSERT      — immutable row in inventory_transactions (never UPDATE)
      5. Balance update     — _update_running_balance() is the ONLY writer to inventory_balances
                             SKIPPED for _BALANCE_NEUTRAL_TYPES (must not affect on_hand)
      6. Outbox event       — InventoryUpdated fired in the SAME transaction

    _BALANCE_NEUTRAL_TYPES (RESERVE, RELEASE, TRANSIT_OUT, TRANSIT_IN, TRANSIT_CLEAR)
    write an audit-trail ledger row but never mutate inventory_balances.
    This prevents RESERVE entries written at PENDING_REVIEW from falsely inflating
    the On Hand balance that inventory_analytics.py reads from inventory_balances.

    Returns the new transaction UUID string.
    """
    tx_id = str(uuid.uuid4())

    # Step 1 — idempotency: 409 on replay
    try:
        await check_and_register_idempotency_key(session, idempotency_key, tx_id)
    except DuplicateTransactionError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "DUPLICATE_TRANSACTION", "idempotency_key": exc.idempotency_key},
        ) from exc

    # Step 2 — pessimistic lock + read balance_before
    balance_before = await _get_balance(
        session, tenant_id, product_id, warehouse_id, lock=True
    )

    # Step 3 — stock floor: skip for audit-only types that don't mutate on_hand.
    # RESERVE (positive) would falsely inflate balance; TRANSIT_CLEAR (negative)
    # would cause a spurious INSUFFICIENT_STOCK error because it doesn't represent
    # a real stock deduction — the TRANSFER_OUT already happened at APPROVED.
    if transaction_type not in _BALANCE_NEUTRAL_TYPES:
        balance_after = balance_before + quantity
        if balance_after < Decimal("0"):
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "INSUFFICIENT_STOCK",
                    "product_id": product_id,
                    "warehouse_id": warehouse_id,
                    "available": float(balance_before),
                    "requested": float(abs(quantity)),
                },
            )

    # Step 4 — INSERT into ledger (never UPDATE)
    await session.execute(
        text(
            "INSERT INTO inventory_transactions "
            "(id, transaction_date, tenant_id, type, product_id, warehouse_id, "
            " quantity, idempotency_key, reference_id, source, created_by) "
            "VALUES (:id, :td, :tid, :type, :pid, :wid, :qty, "
            "        :ikey, :ref, 'WEB', :uid)"
        ),
        {
            "id":   tx_id,
            "td":   date.today(),
            "tid":  tenant_id,
            "type": transaction_type,
            "pid":  product_id,
            "wid":  warehouse_id,
            "qty":  str(quantity),
            "ikey": idempotency_key,
            "ref":  reference_id,
            "uid":  performed_by,
        },
    )

    # Step 5 — update running balance (skip for audit-only types that must not affect on_hand)
    if transaction_type not in _BALANCE_NEUTRAL_TYPES:
        await _update_running_balance(session, tenant_id, product_id, warehouse_id, quantity)

    # Step 6 — outbox event in the SAME transaction (atomicity with ledger INSERT)
    await write_to_outbox(
        session,
        tenant_id,
        "InventoryUpdated",
        InventoryUpdatedPayload(
            product_id=product_id,
            warehouse_id=warehouse_id,
            delta=float(quantity),
            transaction_id=tx_id,
        ),
    )

    return tx_id


# Audit-trail types that write an immutable ledger row but must NOT touch
# inventory_balances.  TRANSFER_REVERSAL is NOT here — it restores on_hand
# when a transfer is cancelled after APPROVED (replacing the old RETURN type).
_BALANCE_NEUTRAL_TYPES: frozenset[str] = frozenset({
    "RESERVE",       # soft-lock at PENDING_REVIEW: on_hand unchanged
    "RELEASE",       # release soft-lock on cancel: on_hand unchanged
    "TRANSIT_OUT",   # dispatch audit at ISSUED: on_hand already deducted at APPROVED
    "TRANSIT_IN",    # inbound audit at IN_TRANSIT: stock not received yet
    "TRANSIT_CLEAR", # clear-transit audit at RECEIVED: TRANSFER_IN handles credit
})

_TRANSFER_LEDGER_TYPES: frozenset[str] = frozenset({
    "RESERVE",
    "RELEASE",
    "TRANSIT_OUT",
    "TRANSIT_IN",
    "TRANSIT_CLEAR",
    "TRANSFER_REVERSAL",
})


async def write_transfer_ledger_entry(
    session: AsyncSession,
    transfer_id: str,
    transaction_type: str,
    quantity: Decimal,
    warehouse_id: str,
    product_id: str,
    tenant_id: str,
    performed_by: str,
    status_transition: str,
    *,
    line_id: Optional[str] = None,
) -> None:
    """Write a single immutable ledger entry for a transfer status transition.

    Idempotency key: {transfer_id}:{transaction_type}:{status_transition}[:{line_id}]
    Pass line_id when the transfer has multiple lines so each line gets a unique key.
    Duplicate-key 409 is caught and swallowed — safe to call on retry.

    Must be called inside the same DB transaction as the status change.
    Never call after session.commit().
    """
    if transaction_type not in _TRANSFER_LEDGER_TYPES:
        raise ValueError(
            f"write_transfer_ledger_entry: unsupported transaction_type {transaction_type!r}. "
            f"Supported: {sorted(_TRANSFER_LEDGER_TYPES)}"
        )

    suffix = f":{line_id}" if line_id else ""
    idempotency_key = f"{transfer_id}:{transaction_type}:{status_transition}{suffix}"

    try:
        await record_transaction(
            session,
            tenant_id=tenant_id,
            transaction_type=transaction_type,
            product_id=product_id,
            warehouse_id=warehouse_id,
            quantity=quantity,
            performed_by=performed_by,
            idempotency_key=idempotency_key,
            reference_type="TRANSFER",
            reference_id=transfer_id,
        )
    except HTTPException as exc:
        if exc.status_code == 409:
            return  # already written — idempotent replay
        raise
