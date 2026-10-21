"""Transfer lot flow — allocate at approval, post per lot, audit per lot, receive.

A transfer line of a batch-tracked product is split into lots ONCE, when the
TRANSFER_OUT is posted (final approval or self-approval). The split is stored
in transfer_line_allocations (085) and every later step reads it back:

  post_transfer_out   allocate (or accept the approver's selection), INSERT the
                      allocation rows, post one TRANSFER_OUT per lot
  post_lot_audit      TRANSIT_OUT / TRANSIT_IN / TRANSIT_CLEAR / TRANSFER_REVERSAL
                      per allocation
  post_transfer_in    one TRANSFER_IN per allocation on the SAME lot_id (for the
                      received quantity when the receipt confirms one)

Non-batch lines post exactly as before (one TRANSFER_OUT, no allocation rows).

Lock order is the same as record_transaction(): the product balance row first,
then the lot_balances rows (ORDER BY lot_id). This module never writes a
balance — every deduction and credit goes through record_transaction().

PERMISSIONS: not checked here. The router resolves can_fefo_override /
can_lot_select and passes them in.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Mapping, Optional, Sequence
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from repositories.ledger_repo import record_transaction, write_transfer_ledger_entry
from services.dispatch_service import (
    DispatchError,
    InsufficientStockError,
    _selection_totals,
    allocate,
    load_candidate_lots,
    load_product,
    plan_allocation,
    record_override,
    resolve_strategy,
    validate_manual_selection,
)


@dataclass(frozen=True)
class Alloc:
    lot_id: str
    lot_number: str
    expiry_date: Optional[date]
    quantity: Decimal
    is_override: bool = False
    product_id: Optional[str] = None


def _get(item: Any, name: str) -> Any:
    return item.get(name) if isinstance(item, dict) else getattr(item, name, None)


async def load_allocations(
    db: AsyncSession,
    tenant_id: UUID | str,
    transfer_id: UUID | str,
) -> dict[str, list[Alloc]]:
    """{line_id: [Alloc, ...]} for a transfer, each list ordered by lot_id.

    A line with no rows is absent from the dict (non-batch line, or a batch
    line whose TRANSFER_OUT has not been posted yet).
    """
    result = await db.execute(
        text(
            "SELECT a.transfer_line_id, a.lot_id, sl.lot_number, sl.expiry_date, "
            "       a.quantity, a.is_override, a.product_id "
            "FROM transfer_line_allocations a "
            "JOIN stock_lots sl ON sl.id = a.lot_id AND sl.tenant_id = a.tenant_id "
            "WHERE a.tenant_id = :tid AND a.transfer_order_id = :xfer_id "
            "ORDER BY a.lot_id"
        ),
        {"tid": str(tenant_id), "xfer_id": str(transfer_id)},
    )
    allocations: dict[str, list[Alloc]] = {}
    for r in result.fetchall():
        allocations.setdefault(str(r.transfer_line_id), []).append(
            Alloc(
                lot_id=str(r.lot_id),
                lot_number=r.lot_number,
                expiry_date=r.expiry_date,
                quantity=Decimal(str(r.quantity)),
                is_override=bool(r.is_override),
                product_id=str(r.product_id),
            )
        )
    return allocations


async def _chosen_allocs(
    db: AsyncSession,
    tenant_id: str,
    product_id: str,
    chosen: Sequence[Any],
) -> list[Alloc]:
    """The user's selection as Allocs (lot number/expiry from stock_lots), by lot_id."""
    totals = _selection_totals(chosen)
    rows = (await db.execute(
        text(
            "SELECT id, lot_number, expiry_date FROM stock_lots "
            "WHERE tenant_id = :tid AND product_id = :pid"
        ),
        {"tid": tenant_id, "pid": product_id},
    )).fetchall()
    lots = {str(r.id): r for r in rows}
    return [
        Alloc(
            lot_id=lot_id,
            lot_number=lots[lot_id].lot_number,
            expiry_date=lots[lot_id].expiry_date,
            quantity=quantity,
        )
        for lot_id, quantity in sorted(totals.items())
    ]


async def _allocate_line(
    db: AsyncSession,
    *,
    tenant_id: str,
    user_id: str,
    transfer_id: str,
    from_warehouse_id: str,
    line: Any,
    product: Any,
    chosen: Optional[Sequence[Any]],
    can_fefo_override: bool,
    can_lot_select: bool,
    reason: Optional[str],
) -> list[Alloc]:
    """Split one batch line into lots and INSERT its transfer_line_allocations rows."""
    product_id = str(line.product_id)
    qty = Decimal(str(line.quantity))

    # Same lock order as record_transaction(): balance row first, then lots.
    await db.execute(
        text(
            "SELECT id FROM inventory_balances "
            "WHERE tenant_id = :tid AND product_id = :pid AND warehouse_id = :wid FOR UPDATE"
        ),
        {"tid": tenant_id, "pid": product_id, "wid": from_warehouse_id},
    )

    strategy, _ = resolve_strategy(
        product.batch_tracking, product.expiry_tracking, product.dispatch_strategy
    )
    is_override = False
    override_id: Optional[str] = None

    if chosen is None:
        try:
            plan = await allocate(db, tenant_id, product_id, from_warehouse_id, qty, strategy)
        except InsufficientStockError as exc:
            # Tell the caller how much of the shortfall is sitting in expired lots.
            lots = await load_candidate_lots(
                db, tenant_id, product_id, from_warehouse_id, lock=False
            )
            exc.expired_qty = sum(  # type: ignore[attr-defined]
                (lot.quantity for lot in plan_allocation(lots, qty, strategy).expired_skipped),
                Decimal("0"),
            )
            raise
        allocs = sorted(
            (
                Alloc(line.lot_id, line.lot_number, line.expiry_date, line.quantity)
                for line in plan.lines
            ),
            key=lambda a: a.lot_id,
        )
    else:
        plan, is_override = await validate_manual_selection(
            db, tenant_id, product_id, from_warehouse_id, qty, chosen, strategy, lock=True
        )
        if is_override:
            permitted = can_fefo_override if strategy == "FEFO" else can_lot_select
            if not permitted:
                raise DispatchError(
                    "OVERRIDE_NOT_PERMITTED", strategy=strategy, line_id=str(line.id)
                )
            override_id = await record_override(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                product_id=product_id,
                warehouse_id=from_warehouse_id,
                strategy=strategy,
                movement_type="TRANSFER",
                reference_id=transfer_id,
                qty=qty,
                plan=plan,
                chosen=chosen,
                reason=reason,
            )
        # The lots posted are the user's chosen lots, not the plan.
        allocs = [
            Alloc(a.lot_id, a.lot_number, a.expiry_date, a.quantity, is_override)
            for a in await _chosen_allocs(db, tenant_id, product_id, chosen)
        ]

    for alloc in allocs:
        await db.execute(
            text(
                "INSERT INTO transfer_line_allocations "
                "(tenant_id, transfer_order_id, transfer_line_id, product_id, lot_id, "
                " from_warehouse_id, quantity, is_override, override_id, created_by) "
                "VALUES (:tid, :xfer_id, :line_id, :pid, :lot_id, "
                "        :wid, :qty, :is_override, :override_id, :uid)"
            ),
            {
                "tid": tenant_id,
                "xfer_id": transfer_id,
                "line_id": str(line.id),
                "pid": product_id,
                "lot_id": alloc.lot_id,
                "wid": from_warehouse_id,
                "qty": str(alloc.quantity),
                "is_override": is_override,
                "override_id": override_id,
                "uid": user_id,
            },
        )
    return allocs


async def post_transfer_out(
    db: AsyncSession,
    *,
    tenant_id: UUID | str,
    user_id: UUID | str,
    transfer_id: UUID | str,
    from_warehouse_id: UUID | str,
    lines: Sequence[Any],
    key_prefix: str,
    selections: Optional[Sequence[Any]] = None,
    can_fefo_override: bool = False,
    can_lot_select: bool = False,
    reason: Optional[str] = None,
) -> None:
    """Post the source deduction for every line of a transfer.

    Lines are processed ORDER BY (product_id, line id), strictly one after
    another, so a second line of the same product sees the first line's debits.

    Non-batch line: one TRANSFER_OUT, key f"{key_prefix}:line:{line.id}".
    Batch line:     one TRANSFER_OUT per lot, key
                    f"{key_prefix}:line:{line.id}:lot:{lot_id}". The lots come
                    from the line's stored allocations when they already exist
                    (a replay — nothing is allocated again, and lots already
                    posted are skipped), otherwise from the engine or from the
                    approver's selection.

    selections: items exposing line_id and lots (each lot: lot_id, quantity).
    Raises DispatchError / InsufficientStockError — callers map them with
    http_from_engine().
    """
    tenant_id, user_id = str(tenant_id), str(user_id)
    transfer_id, from_warehouse_id = str(transfer_id), str(from_warehouse_id)

    ordered = sorted(lines, key=lambda line: (str(line.product_id), str(line.id)))
    line_ids = {str(line.id) for line in ordered}

    chosen_by_line: dict[str, list[Any]] = {}
    for selection in selections or []:
        line_id = str(_get(selection, "line_id"))
        if line_id not in line_ids:
            raise DispatchError("SELECTION_QTY_MISMATCH", line_id=line_id)
        chosen_by_line.setdefault(line_id, []).extend(_get(selection, "lots") or [])

    existing = await load_allocations(db, tenant_id, transfer_id)

    for line in ordered:
        line_id = str(line.id)
        product_id = str(line.product_id)
        product = await load_product(db, tenant_id, product_id)

        if not product.batch_tracking:
            if line_id in chosen_by_line:
                raise DispatchError("LOT_NOT_TRACKED", line_id=line_id)
            await record_transaction(
                db,
                tenant_id=tenant_id,
                transaction_type="TRANSFER_OUT",
                product_id=product_id,
                warehouse_id=from_warehouse_id,
                quantity=-Decimal(str(line.quantity)),
                performed_by=user_id,
                idempotency_key=f"{key_prefix}:line:{line.id}",
                reference_id=transfer_id,
            )
            continue

        replay = line_id in existing
        if replay:
            allocs = existing[line_id]
        else:
            allocs = await _allocate_line(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                transfer_id=transfer_id,
                from_warehouse_id=from_warehouse_id,
                line=line,
                product=product,
                chosen=chosen_by_line.get(line_id),
                can_fefo_override=can_fefo_override,
                can_lot_select=can_lot_select,
                reason=reason,
            )

        for alloc in allocs:
            try:
                await record_transaction(
                    db,
                    tenant_id=tenant_id,
                    transaction_type="TRANSFER_OUT",
                    product_id=product_id,
                    warehouse_id=from_warehouse_id,
                    quantity=-alloc.quantity,
                    performed_by=user_id,
                    idempotency_key=f"{key_prefix}:line:{line.id}:lot:{alloc.lot_id}",
                    reference_id=transfer_id,
                    lot_id=alloc.lot_id,
                    lot_number=alloc.lot_number,
                    expiry_date=alloc.expiry_date,
                )
            except HTTPException as exc:
                if replay and exc.status_code == 409:
                    continue  # this lot was already posted — idempotent replay
                raise


async def post_lot_audit(
    db: AsyncSession,
    *,
    tenant_id: UUID | str,
    user_id: UUID | str,
    transfer_id: UUID | str,
    line: Any,
    allocs: Sequence[Alloc],
    transaction_type: str,
    warehouse_id: UUID | str,
    sign: int,
    status_transition: str,
    dest: bool = False,
) -> None:
    """One transfer ledger entry per allocation of a batch line.

    For TRANSIT_OUT / TRANSIT_IN / TRANSIT_CLEAR (audit only) and
    TRANSFER_REVERSAL (puts each lot back at the source). sign is +1 or -1.
    The key suffix is "{line.id}:{lot_id}" (":dest" appended when dest=True),
    so every entry has a unique idempotency key.
    """
    for alloc in allocs:
        suffix = f"{line.id}:{alloc.lot_id}"
        await write_transfer_ledger_entry(
            session=db,
            transfer_id=str(transfer_id),
            transaction_type=transaction_type,
            quantity=alloc.quantity * sign,
            warehouse_id=str(warehouse_id),
            product_id=str(line.product_id),
            tenant_id=str(tenant_id),
            performed_by=str(user_id),
            status_transition=status_transition,
            line_id=f"{suffix}:dest" if dest else suffix,
            lot_id=alloc.lot_id,
            lot_number=alloc.lot_number,
            expiry_date=alloc.expiry_date,
        )


async def post_transfer_in(
    db: AsyncSession,
    *,
    tenant_id: UUID | str,
    user_id: UUID | str,
    transfer_id: UUID | str,
    to_warehouse_id: UUID | str,
    line: Any,
    allocs: Sequence[Alloc],
    received_by_lot: Optional[Mapping[str, Decimal]] = None,
) -> None:
    """Credit the destination: one TRANSFER_IN per allocation.

    The credit upserts lot_balances on the SAME lot_id the source was debited
    on, so lot number, expiry and first_received_at carry over unchanged.

    received_by_lot ({lot_id: quantity}, receipt confirmation) credits that
    quantity instead of the allocated one; a lot that received 0 gets no
    TRANSFER_IN. Without it every lot is credited in full.
    """
    for alloc in allocs:
        quantity = alloc.quantity if received_by_lot is None else received_by_lot[alloc.lot_id]
        if quantity <= 0:
            continue
        await record_transaction(
            db,
            tenant_id=str(tenant_id),
            transaction_type="TRANSFER_IN",
            product_id=str(line.product_id),
            warehouse_id=str(to_warehouse_id),
            quantity=quantity,
            performed_by=str(user_id),
            idempotency_key=f"transfer:{transfer_id}:receive:in:line:{line.id}:lot:{alloc.lot_id}",
            reference_id=str(transfer_id),
            lot_id=alloc.lot_id,
            lot_number=alloc.lot_number,
            expiry_date=alloc.expiry_date,
        )


def http_from_engine(exc: Exception) -> HTTPException:
    """Map a dispatch-engine error to the HTTP error the transfer endpoints return."""
    if isinstance(exc, InsufficientStockError):
        return HTTPException(
            status_code=422,
            detail={
                "code": "INSUFFICIENT_STOCK",
                "product_id": str(exc.product_id),
                "requested": float(exc.required),
                "available": float(exc.available),
                "expired_qty": float(getattr(exc, "expired_qty", Decimal("0"))),
            },
        )
    if isinstance(exc, DispatchError):
        status_code = 403 if exc.code == "OVERRIDE_NOT_PERMITTED" else 422
        return HTTPException(status_code=status_code, detail={"code": exc.code, **exc.detail})
    raise TypeError(f"http_from_engine: unsupported exception {type(exc).__name__}")
