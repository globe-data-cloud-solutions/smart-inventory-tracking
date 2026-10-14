"""Inventory ledger repository — the ONLY permitted writer to inventory_balances.

All stock mutations MUST flow through record_transaction(). No other code path
may issue a direct INSERT/UPDATE to inventory_balances.

Two balance writers exist, both reachable only from record_transaction():
  _update_running_balance() — the product/warehouse total in inventory_balances
  _update_lot_balance()     — the per-lot/warehouse total in lot_balances (lot_repo.py)

Enforcement chain (CLAUDE.md §14, Business Rules #2, #26):
  1. Application rule: only record_transaction() may call _update_running_balance()
                       or _update_lot_balance()
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

from repositories.lot_repo import _get_lot_balance, _update_lot_balance
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
    lot_number: Optional[str] = None,
    expiry_date: Optional[date] = None,
    source: str = "WEB",
    unit_cost: Optional[Decimal] = None,
) -> str:
    """Record an immutable ledger entry and conditionally update the running balance.

    Single entry point for all inventory mutations. Sequence within ONE transaction:
      0. Zero guard         — HTTP 422 ZERO_QUANTITY when quantity == 0; callers
                             that can arrive at 0 (e.g. a receipt line received
                             as 0) skip the call themselves
      1. Idempotency guard  — HTTP 409 on duplicate key
      2. Pessimistic lock   — FOR UPDATE on balance row prevents concurrent races
      2b. Lot guard         — when the product is batch_tracking and the type is not
                             balance-neutral: HTTP 422 LOT_REQUIRED if lot_id is missing;
                             HTTP 422 LOT_NOT_TRACKED if lot_id is given for a non-batch
                             product. SKIPPED for _BALANCE_NEUTRAL_TYPES.
      3. Stock floor check  — HTTP 422 when balance + quantity would go negative
                             SKIPPED for _BALANCE_NEUTRAL_TYPES (audit-only entries)
                             and for _LOT_ONLY_TYPES (product total unaffected)
      3b. Lot floor check   — when lot_id is given and the type is not neutral: lock
                             the lot_balances row FOR UPDATE and reject with HTTP 422
                             INSUFFICIENT_LOT_STOCK if it would go negative. The
                             product-level floor check above is unaffected.
      4. Ledger INSERT      — immutable row in inventory_transactions (never UPDATE);
                             always carries lot_id/lot_number/expiry_date (NULL if unset)
      5. Balance update     — _update_running_balance() is the ONLY writer to inventory_balances
                             SKIPPED for _BALANCE_NEUTRAL_TYPES (must not affect on_hand)
                             and for _LOT_ONLY_TYPES (product total seeded separately)
      5b. Lot balance update — _update_lot_balance() is the ONLY writer to lot_balances,
                             called when lot_id is given and the type is not neutral.
                             Neutral types with lot_id write the lot columns onto the
                             ledger row but never touch lot_balances. _LOT_ONLY_TYPES
                             always update the lot balance (lot_id is required for them).
      6. Outbox event       — InventoryUpdated fired in the SAME transaction

    _BALANCE_NEUTRAL_TYPES (RESERVE, RELEASE, TRANSIT_OUT, TRANSIT_IN, TRANSIT_CLEAR)
    write an audit-trail ledger row but never mutate inventory_balances.
    This prevents RESERVE entries written at PENDING_REVIEW from falsely inflating
    the On Hand balance that inventory_analytics.py reads from inventory_balances.

    _LOT_ONLY_TYPES (LOT_OPENING) capture a lot's opening quantity: they require
    a lot_id, update only lot_balances, and never touch inventory_balances — the
    product-level total is seeded separately (RECEIVE/ADJUSTMENT/opening import).

    Returns the new transaction UUID string.
    """
    # Step 0 — a zero-quantity ledger row is never written
    if quantity == 0:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "ZERO_QUANTITY",
                "product_id": product_id,
                "transaction_type": transaction_type,
            },
        )

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

    # Step 2b — lot guard: batch-tracked products must carry a lot_id for any
    # type that isn't balance-neutral (RESERVE/RELEASE/TRANSIT_* stay allowed
    # without a lot); non-batch products must never carry one.
    if transaction_type in _LOT_ONLY_TYPES:
        if lot_id is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "LOT_REQUIRED",
                    "product_id": product_id,
                    "transaction_type": transaction_type,
                },
            )
    elif transaction_type not in _BALANCE_NEUTRAL_TYPES:
        product_row = (
            await session.execute(
                text(
                    "SELECT batch_tracking FROM products "
                    "WHERE id = :pid AND tenant_id = :tid FOR SHARE"
                ),
                {"pid": product_id, "tid": tenant_id},
            )
        ).fetchone()
        batch_tracking = bool(product_row.batch_tracking) if product_row else False

        if batch_tracking and lot_id is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "LOT_REQUIRED",
                    "product_id": product_id,
                    "transaction_type": transaction_type,
                },
            )
        if not batch_tracking and lot_id is not None:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "LOT_NOT_TRACKED",
                    "product_id": product_id,
                    "transaction_type": transaction_type,
                },
            )

    # Step 3 — stock floor: skip for audit-only types that don't mutate on_hand,
    # and for lot-only types whose product total is unaffected.
    # RESERVE (positive) would falsely inflate balance; TRANSIT_CLEAR (negative)
    # would cause a spurious INSUFFICIENT_STOCK error because it doesn't represent
    # a real stock deduction — the TRANSFER_OUT already happened at APPROVED.
    if transaction_type not in _BALANCE_NEUTRAL_TYPES and transaction_type not in _LOT_ONLY_TYPES:
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

    # Step 3b — lot floor: lock the lot_balances row and reject a negative lot
    # balance, independent of the product-level floor check above.
    if lot_id is not None and transaction_type not in _BALANCE_NEUTRAL_TYPES:
        lot_balance_before = await _get_lot_balance(
            session, tenant_id, lot_id, warehouse_id, lock=True
        )
        lot_balance_after = lot_balance_before + quantity
        if lot_balance_after < Decimal("0"):
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "INSUFFICIENT_LOT_STOCK",
                    "lot_id": lot_id,
                    "warehouse_id": warehouse_id,
                    "available": float(lot_balance_before),
                    "requested": float(abs(quantity)),
                },
            )

    # Step 4 — INSERT into ledger (never UPDATE)
    await session.execute(
        text(
            "INSERT INTO inventory_transactions "
            "(id, transaction_date, tenant_id, type, product_id, warehouse_id, "
            " quantity, idempotency_key, reference_id, source, created_by, "
            " lot_id, lot_number, expiry_date, unit_cost) "
            "VALUES (:id, :td, :tid, :type, :pid, :wid, :qty, "
            "        :ikey, :ref, :source, :uid, :lot_id, :lot_number, :expiry_date, :unit_cost)"
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
            "source": source,
            "uid":  performed_by,
            "lot_id":      lot_id,
            "lot_number":  lot_number,
            "expiry_date": expiry_date,
            "unit_cost":   str(unit_cost) if unit_cost is not None else None,
        },
    )

    # Step 5 — update running balance (skip for audit-only types that must not
    # affect on_hand, and for lot-only types whose product total is seeded
    # separately)
    if (
        transaction_type not in _BALANCE_NEUTRAL_TYPES
        and transaction_type not in _LOT_ONLY_TYPES
    ):
        await _update_running_balance(session, tenant_id, product_id, warehouse_id, quantity)

        # Step 5b — update lot balance (skip for neutral types; they write the
        # lot columns on the ledger row above but never touch lot_balances)
        if lot_id is not None:
            await _update_lot_balance(session, tenant_id, lot_id, product_id, warehouse_id, quantity)
    elif transaction_type in _LOT_ONLY_TYPES:
        # Lot-only types always carry a lot_id (enforced in Step 2b) and only
        # ever touch lot_balances — the product total is unaffected.
        await _update_lot_balance(session, tenant_id, lot_id, product_id, warehouse_id, quantity)

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

# Lot-only types: always require a lot_id, write the ledger row and update
# lot_balances, but never touch inventory_balances — the product total is
# seeded separately (RECEIVE/ADJUSTMENT/opening import).
_LOT_ONLY_TYPES: frozenset[str] = frozenset({
    "LOT_OPENING",   # captures a lot's opening quantity; product total unchanged
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
    lot_id: Optional[str] = None,
    lot_number: Optional[str] = None,
    expiry_date: Optional[date] = None,
) -> None:
    """Write a single immutable ledger entry for a transfer status transition.

    Idempotency key: {transfer_id}:{transaction_type}:{status_transition}[:{line_id}]
    Pass line_id when the transfer has multiple lines so each line gets a unique key.
    Duplicate-key 409 is caught and swallowed — safe to call on retry.

    lot_id/lot_number/expiry_date are passed through to record_transaction() for
    lot-aware transfers; no existing caller passes them yet.

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
            lot_id=lot_id,
            lot_number=lot_number,
            expiry_date=expiry_date,
        )
    except HTTPException as exc:
        if exc.status_code == 409:
            return  # already written — idempotent replay
        raise
