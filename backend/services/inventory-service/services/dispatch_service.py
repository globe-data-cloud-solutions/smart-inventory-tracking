"""Dispatch engine — strategy resolution, lot ordering, allocation, override log.

Two layers:
  Pure (no DB)  resolve_strategy, sort_lots, plan_allocation, compare_selection.
  DB            load_candidate_lots, load_product, allocate,
                validate_manual_selection, record_override.

Lots come from lot_balances JOIN stock_lots (081). This module never writes a
balance: it only decides WHICH lots a movement should draw from. The caller
still posts every deduction through record_transaction() in ledger_repo.py.

Strategy resolution (category strategy is PARKED — categories and the archived
dispatch_strategy_configs table are never read here):
  not batch-tracked            -> (None,   "NOT_BATCH")
  expiry-tracked               -> ("FEFO", "FORCED")
  products.dispatch_strategy   -> (it,     "PRODUCT")
  otherwise                    -> ("FIFO", "DEFAULT")
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable, List, Optional, Sequence, Tuple
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

STRATEGIES = ("FEFO", "FIFO", "LIFO")


class InsufficientStockError(Exception):
    def __init__(self, product_id: UUID, required: Decimal, available: Decimal) -> None:
        super().__init__(
            f"Insufficient stock for {product_id}: required={required}, available={available}"
        )
        self.product_id = product_id
        self.required = required
        self.available = available


class DispatchError(Exception):
    """Domain error carrying a stable code. Routers translate it to HTTP."""

    def __init__(self, code: str, **detail: Any) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


# ── Pure layer ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CandidateLot:
    lot_id: str
    lot_number: str
    expiry_date: Optional[date]
    first_received_at: datetime
    quantity: Decimal


@dataclass(frozen=True)
class AllocationLine:
    lot_id: str
    lot_number: str
    expiry_date: Optional[date]
    quantity: Decimal


@dataclass
class Allocation:
    lines: List[AllocationLine] = field(default_factory=list)
    shortfall: Decimal = Decimal("0")
    expired_skipped: List[AllocationLine] = field(default_factory=list)


@dataclass(frozen=True)
class ProductDispatchInfo:
    batch_tracking: bool
    expiry_tracking: bool
    dispatch_strategy: Optional[str]


def resolve_strategy(
    batch_tracking: bool,
    expiry_tracking: bool,
    product_strategy: Optional[str],
) -> Tuple[Optional[str], str]:
    """Return (strategy, source). See the module docstring for the order."""
    if not batch_tracking:
        return None, "NOT_BATCH"
    if expiry_tracking:
        return "FEFO", "FORCED"
    if product_strategy:
        return product_strategy, "PRODUCT"
    return "FIFO", "DEFAULT"


def sort_lots(lots: Iterable[CandidateLot], strategy: str) -> List[CandidateLot]:
    """Deterministic dispatch order.

    FEFO: lots with NO expiry first (OPENING and pre-expiry-tracking lots),
          then expiry_date asc, first_received_at asc, lot_number asc.
    FIFO: first_received_at asc, lot_number asc.
    LIFO: first_received_at desc, lot_number asc.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown dispatch strategy: {strategy!r}")

    by_number = sorted(lots, key=lambda lot: lot.lot_number)
    if strategy == "FEFO":
        return sorted(
            by_number,
            key=lambda lot: (
                lot.expiry_date is not None,
                lot.expiry_date or date.min,
                lot.first_received_at,
            ),
        )
    # sorted() is stable (also with reverse=True), so lot_number asc survives as the tie-break.
    return sorted(by_number, key=lambda lot: lot.first_received_at, reverse=(strategy == "LIFO"))


def _line(lot: CandidateLot, quantity: Decimal) -> AllocationLine:
    return AllocationLine(
        lot_id=str(lot.lot_id),
        lot_number=lot.lot_number,
        expiry_date=lot.expiry_date,
        quantity=quantity,
    )


def plan_allocation(
    lots: Iterable[CandidateLot],
    qty: Decimal,
    strategy: str,
    today: Optional[date] = None,
) -> Allocation:
    """Walk the lots in strategy order until qty is covered. Never raises on stock.

    Lots with expiry_date < today are NEVER allocated — they are reported in
    expired_skipped. Zero-quantity lots are ignored. shortfall is the part of
    qty the non-expired lots could not cover (0 when fully covered).
    """
    today = today or date.today()
    plan = Allocation()
    remaining = max(Decimal(qty), Decimal("0"))

    for lot in sort_lots(lots, strategy):
        if lot.quantity <= 0:
            continue
        if lot.expiry_date is not None and lot.expiry_date < today:
            plan.expired_skipped.append(_line(lot, lot.quantity))
            continue
        if remaining <= 0:
            continue
        take = min(lot.quantity, remaining)
        plan.lines.append(_line(lot, take))
        remaining -= take

    plan.shortfall = remaining
    return plan


def _get(item: Any, name: str) -> Any:
    return item.get(name) if isinstance(item, dict) else getattr(item, name, None)


def _selection_totals(chosen: Iterable[Any]) -> dict[str, Decimal]:
    """Collapse a selection to {lot_id: total quantity}, dropping zero lines."""
    totals: dict[str, Decimal] = {}
    for item in chosen:
        lot_id = str(_get(item, "lot_id"))
        totals[lot_id] = totals.get(lot_id, Decimal("0")) + Decimal(str(_get(item, "quantity")))
    return {k: v for k, v in totals.items() if v != 0}


def compare_selection(plan: Allocation, chosen: Iterable[Any]) -> bool:
    """is_override: True when the chosen lot/quantity set differs from plan.lines.

    Order within the selection does not matter — only which lots and how much.
    """
    return _selection_totals(chosen) != _selection_totals(plan.lines)


# ── DB layer ──────────────────────────────────────────────────────────────────

async def load_candidate_lots(
    db: AsyncSession,
    tenant_id: Optional[UUID | str],
    product_id: UUID | str,
    warehouse_id: UUID | str,
    lock: bool = False,
) -> List[CandidateLot]:
    """Lots of this product holding stock (quantity > 0) in this warehouse.

    lock=True first locks the product's lot_balances rows in this warehouse
    ORDER BY lot_id FOR UPDATE — a fixed order, so two concurrent allocations
    can never deadlock — and only then reads. The preview never locks.

    tenant_id=None (SA spanning tenants on the read replica) drops the tenant
    predicate, as get_lots() does; write paths always pass a tenant.
    """
    params = {"pid": str(product_id), "wid": str(warehouse_id)}
    tenant_clause = ""
    if tenant_id is not None:
        tenant_clause = "AND lb.tenant_id = :tid"
        params["tid"] = str(tenant_id)

    if lock:
        await db.execute(
            text(
                "SELECT lb.id FROM lot_balances lb "
                f"WHERE lb.product_id = :pid AND lb.warehouse_id = :wid {tenant_clause} "
                "ORDER BY lb.lot_id FOR UPDATE"
            ),
            params,
        )

    result = await db.execute(
        text(
            "SELECT sl.id AS lot_id, sl.lot_number, sl.expiry_date, "
            "       sl.first_received_at, lb.quantity "
            "FROM lot_balances lb "
            "JOIN stock_lots sl ON sl.id = lb.lot_id AND sl.tenant_id = lb.tenant_id "
            f"WHERE lb.product_id = :pid AND lb.warehouse_id = :wid {tenant_clause} "
            "AND lb.quantity > 0 "
            "ORDER BY lb.lot_id"
        ),
        params,
    )
    return [
        CandidateLot(
            lot_id=str(r.lot_id),
            lot_number=r.lot_number,
            expiry_date=r.expiry_date,
            first_received_at=r.first_received_at,
            quantity=Decimal(str(r.quantity)),
        )
        for r in result.fetchall()
    ]


async def load_product(
    db: AsyncSession,
    tenant_id: Optional[UUID | str],
    product_id: UUID | str,
) -> ProductDispatchInfo:
    params = {"pid": str(product_id)}
    tenant_clause = ""
    if tenant_id is not None:
        tenant_clause = "AND tenant_id = :tid"
        params["tid"] = str(tenant_id)

    row = (await db.execute(
        text(
            "SELECT batch_tracking, expiry_tracking, dispatch_strategy FROM products "
            f"WHERE id = :pid {tenant_clause}"
        ),
        params,
    )).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "PRODUCT_NOT_FOUND"})

    return ProductDispatchInfo(
        batch_tracking=bool(row.batch_tracking),
        expiry_tracking=bool(row.expiry_tracking),
        dispatch_strategy=row.dispatch_strategy,
    )


async def allocate(
    db: AsyncSession,
    tenant_id: UUID | str,
    product_id: UUID | str,
    warehouse_id: UUID | str,
    qty: Decimal,
    strategy: str,
    today: Optional[date] = None,
) -> Allocation:
    """Lock the candidate lots and plan qty against them (Phase C callers).

    Must run inside the caller's write transaction: the row locks taken here
    are what keep the plan valid until the caller posts its ledger rows.
    Raises InsufficientStockError when the non-expired lots cannot cover qty.
    """
    lots = await load_candidate_lots(db, tenant_id, product_id, warehouse_id, lock=True)
    plan = plan_allocation(lots, qty, strategy, today)
    if plan.shortfall > 0:
        raise InsufficientStockError(
            UUID(str(product_id)), Decimal(qty), Decimal(qty) - plan.shortfall
        )
    return plan


async def validate_manual_selection(
    db: AsyncSession,
    tenant_id: UUID | str,
    product_id: UUID | str,
    warehouse_id: UUID | str,
    qty: Decimal,
    chosen: Sequence[Any],
    strategy: str,
    today: Optional[date] = None,
    lock: bool = True,
) -> Tuple[Allocation, bool]:
    """Check a user's lot selection and return (engine plan, is_override).

    chosen: items exposing lot_id and quantity (dicts or objects). Raises
    DispatchError with one of:
      LOT_NOT_IN_WAREHOUSE    lot does not hold stock of this product in this warehouse
      LOT_EXPIRED             lot's expiry_date is before today
      INSUFFICIENT_LOT_STOCK  chosen quantity exceeds the lot's balance
      SELECTION_QTY_MISMATCH  a non-positive line, or the lines do not sum to qty
    """
    today = today or date.today()
    lots = await load_candidate_lots(db, tenant_id, product_id, warehouse_id, lock=lock)
    by_id = {lot.lot_id: lot for lot in lots}

    for item in chosen:
        if Decimal(str(_get(item, "quantity"))) <= 0:
            raise DispatchError("SELECTION_QTY_MISMATCH", lot_id=str(_get(item, "lot_id")))

    totals = _selection_totals(chosen)
    for lot_id, quantity in totals.items():
        lot = by_id.get(lot_id)
        if lot is None:
            raise DispatchError("LOT_NOT_IN_WAREHOUSE", lot_id=lot_id)
        if lot.expiry_date is not None and lot.expiry_date < today:
            raise DispatchError("LOT_EXPIRED", lot_id=lot_id, lot_number=lot.lot_number)
        if quantity > lot.quantity:
            raise DispatchError(
                "INSUFFICIENT_LOT_STOCK",
                lot_id=lot_id,
                lot_number=lot.lot_number,
                available=str(lot.quantity),
                requested=str(quantity),
            )

    selected = sum(totals.values(), Decimal("0"))
    if selected != Decimal(qty):
        raise DispatchError(
            "SELECTION_QTY_MISMATCH", requested=str(qty), selected=str(selected)
        )

    plan = plan_allocation(lots, qty, strategy, today)
    return plan, compare_selection(plan, chosen)


async def record_override(
    db: AsyncSession,
    tenant_id: UUID | str,
    user_id: UUID | str,
    product_id: UUID | str,
    warehouse_id: UUID | str,
    strategy: str,
    movement_type: str,
    reference_id: Optional[UUID | str],
    qty: Decimal,
    plan: Allocation,
    chosen: Sequence[Any],
    reason: Optional[str],
) -> str:
    """INSERT one lot_allocation_overrides row; returns its id.

    The table is append-only by code: this INSERT is the only writer — no
    update or delete function exists. Runs in the caller's transaction.

    A FEFO override needs a non-blank reason (DispatchError
    OVERRIDE_REASON_REQUIRED); for FIFO/LIFO the reason is optional.

    PERMISSIONS: this function does not check them. The CALLER must check
    PERMISSIONS.DISPATCH_FEFO_OVERRIDE before recording a FEFO override and
    PERMISSIONS.DISPATCH_LOT_SELECT before recording a FIFO/LIFO override.
    Phase C wires the callers.
    """
    reason = (reason or "").strip() or None
    if strategy == "FEFO" and reason is None:
        raise DispatchError("OVERRIDE_REASON_REQUIRED")

    totals = _selection_totals(chosen)
    rows = (await db.execute(
        text(
            "SELECT id, lot_number FROM stock_lots "
            "WHERE tenant_id = :tid AND product_id = :pid"
        ),
        {"tid": str(tenant_id), "pid": str(product_id)},
    )).fetchall()
    lot_numbers = {str(r.id): r.lot_number for r in rows}

    suggested = [
        {"lot_id": line.lot_id, "lot_number": line.lot_number, "quantity": str(line.quantity)}
        for line in plan.lines
    ]
    chosen_json = [
        {"lot_id": lot_id, "lot_number": lot_numbers.get(lot_id), "quantity": str(quantity)}
        for lot_id, quantity in totals.items()
    ]

    result = await db.execute(
        text(
            "INSERT INTO lot_allocation_overrides "
            "(tenant_id, product_id, warehouse_id, strategy, movement_type, reference_id, "
            " requested_qty, suggested, chosen, reason, overridden_by) "
            "VALUES (:tid, :pid, :wid, CAST(:strategy AS dispatch_strategy), :mtype, :ref, "
            "        :qty, CAST(:suggested AS jsonb), CAST(:chosen AS jsonb), :reason, :uid) "
            "RETURNING id"
        ),
        {
            "tid": str(tenant_id),
            "pid": str(product_id),
            "wid": str(warehouse_id),
            "strategy": strategy,
            "mtype": movement_type,
            "ref": str(reference_id) if reference_id else None,
            "qty": str(qty),
            "suggested": json.dumps(suggested),
            "chosen": json.dumps(chosen_json),
            "reason": reason,
            "uid": str(user_id),
        },
    )
    return str(result.fetchone().id)
