"""Transfer receipt confirmation — what arrived, and what did not — and the
later resolution of each shortfall.

The destination confirms a received quantity per allocated lot (batch line) or
per line (non-batch line). A quantity below what was sent becomes one row in
transfer_discrepancies (086); TRANSFER_IN credits the received quantity only.

  validate_receipt     check the whole receipt body against the transfer,
                       before anything is written
  insert_discrepancy   the ONLY insert path to transfer_discrepancies
  load_discrepancies   the rows of a transfer, with the lot numbers
  resolve_discrepancy  the ONLY update path: OPEN -> RESOLVED, exactly once
  list_discrepancies   the tenant's rows across transfers (GET /discrepancies)

Rows are inserted OPEN at receipt and updated exactly once, OPEN -> RESOLVED,
by resolve_discrepancy() (088) — a documented exception to 086's
append-only-by-code rule. Every resolution writes its ledger rows, the UPDATE
and an audit_logs row in ONE transaction. There is no delete path.

Resolutions (N = missing_quantity):
  WRITTEN_OFF      the stock is lost: no ledger rows, a note is required
  RETURNED         it went back to the source: TRANSFER_REVERSAL +N at source
  ARRIVED_LATE     it turned up at the destination: TRANSFER_IN +N at destination
  RECEIVED_AS_LOT  a different lot of the product arrived (WRONG_LOT, batch line):
                   TRANSFER_REVERSAL +N at source on the sent lot, TRANSFER_OUT -N
                   at source on the arrived lot, TRANSFER_IN +N at destination on
                   the arrived lot

PERMISSIONS: receipt — not checked here; the router requires transfer:receive
and InventoryService.receive_transfer() runs the destination-warehouse check.
Resolution — the router requires transfer:resolve_discrepancy and
resolve_discrepancy() checks the RM's node subtree (TA / NM / SA: tenant-wide).
Listing — the router requires transfer:list and list_discrepancies() narrows
facility-scoped roles, and an RM with a node, to their node subtree.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any, Iterable, Mapping, Optional, Sequence
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from repositories.ledger_repo import record_transaction
from schemas.inventory import (
    ReceiptLineIn,
    ResolveDiscrepancyRequest,
    TransferDiscrepancyListItem,
    TransferDiscrepancyOut,
)
from shared.permissions.hierarchy_service import get_descendant_node_ids

# (line_id, lot_id) — lot_id is None for a non-batch line.
EntryKey = tuple[str, Optional[str]]


def expected_entries(
    lines: Sequence[Any],
    allocations: Mapping[str, Sequence[Any]],
) -> dict[EntryKey, Decimal]:
    """{(line_id, lot_id): sent quantity} — what a receipt body must cover.

    A batch line yields one entry per allocation, a non-batch line one entry
    with lot_id None.
    """
    expected: dict[EntryKey, Decimal] = {}
    for line in lines:
        line_id = str(line.id)
        line_allocs = allocations.get(line_id)
        if line_allocs:
            for alloc in line_allocs:
                expected[(line_id, str(alloc.lot_id))] = Decimal(str(alloc.quantity))
        else:
            expected[(line_id, None)] = Decimal(str(line.quantity))
    return expected


def validate_receipt(
    expected: Mapping[EntryKey, Decimal],
    receipt_lines: Sequence[ReceiptLineIn],
) -> dict[EntryKey, ReceiptLineIn]:
    """The receipt body keyed like `expected`. Raises 422 and writes nothing.

    RECEIPT_LINES_MISMATCH   the body does not list every expected entry exactly once
    RECEIPT_EXCEEDS_SENT     received more than was sent
    WRONG_LOT_NOT_BATCH      WRONG_LOT on a non-batch entry (lot_id None)
    RECEIPT_REASON_REQUIRED  received less than was sent and no reason given
    """
    keys: list[EntryKey] = [
        (str(e.line_id), str(e.lot_id) if e.lot_id is not None else None) for e in receipt_lines
    ]
    if len(set(keys)) != len(keys) or set(keys) != set(expected):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "RECEIPT_LINES_MISMATCH",
                "expected": [
                    {"line_id": line_id, "lot_id": lot_id} for line_id, lot_id in expected
                ],
            },
        )

    entries = dict(zip(keys, receipt_lines))
    for (line_id, lot_id), sent in expected.items():
        entry = entries[(line_id, lot_id)]
        if entry.received_quantity > sent:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "RECEIPT_EXCEEDS_SENT",
                    "line_id": line_id,
                    "lot_id": lot_id,
                    "sent": float(sent),
                    "received": float(entry.received_quantity),
                },
            )
        if lot_id is None and entry.reason == "WRONG_LOT":
            raise HTTPException(
                status_code=422,
                detail={"code": "WRONG_LOT_NOT_BATCH", "line_id": line_id, "lot_id": None},
            )
        if entry.received_quantity < sent and entry.reason is None:
            raise HTTPException(
                status_code=422,
                detail={"code": "RECEIPT_REASON_REQUIRED", "line_id": line_id, "lot_id": lot_id},
            )
    return entries


async def insert_discrepancy(
    db: AsyncSession,
    *,
    tenant_id: UUID | str,
    transfer_id: UUID | str,
    line_id: UUID | str,
    product_id: UUID | str,
    lot_id: Optional[UUID | str],
    to_warehouse_id: UUID | str,
    sent_quantity: Decimal,
    received_quantity: Decimal,
    reason: str,
    note: Optional[str],
    created_by: UUID | str,
) -> None:
    """INSERT one OPEN discrepancy: missing = sent - received (must be > 0)."""
    await db.execute(
        text(
            "INSERT INTO transfer_discrepancies "
            "(tenant_id, transfer_order_id, transfer_line_id, product_id, lot_id, "
            " to_warehouse_id, sent_quantity, received_quantity, missing_quantity, "
            " reason, note, created_by) "
            "VALUES (:tid, :xfer_id, :line_id, :pid, :lot_id, "
            "        :wid, :sent, :received, :missing, :reason, :note, :uid)"
        ),
        {
            "tid": str(tenant_id),
            "xfer_id": str(transfer_id),
            "line_id": str(line_id),
            "pid": str(product_id),
            "lot_id": str(lot_id) if lot_id is not None else None,
            "wid": str(to_warehouse_id),
            "sent": str(sent_quantity),
            "received": str(received_quantity),
            "missing": str(sent_quantity - received_quantity),
            "reason": reason,
            "note": note,
            "uid": str(created_by),
        },
    )


# Columns of TransferDiscrepancyOut: the sent lot (sl) and the resolved lot (rl)
# are both LEFT JOINed for their lot numbers.
_DISCREPANCY_COLUMNS = (
    "d.id, d.transfer_line_id, d.product_id, d.lot_id, sl.lot_number, "
    "d.sent_quantity, d.received_quantity, d.missing_quantity, "
    "d.reason, d.note, d.status, d.created_at, "
    "d.resolution, d.resolved_lot_id, rl.lot_number AS resolved_lot_number, "
    "d.resolution_note, d.resolved_by, d.resolved_at"
)
_DISCREPANCY_LOT_JOINS = (
    "LEFT JOIN stock_lots sl ON sl.id = d.lot_id AND sl.tenant_id = d.tenant_id "
    "LEFT JOIN stock_lots rl ON rl.id = d.resolved_lot_id AND rl.tenant_id = d.tenant_id "
)


def _discrepancy_fields(r: Any) -> dict[str, Any]:
    return {
        "id": r.id,
        "transfer_line_id": r.transfer_line_id,
        "product_id": r.product_id,
        "lot_id": r.lot_id,
        "lot_number": r.lot_number,
        "sent_quantity": r.sent_quantity,
        "received_quantity": r.received_quantity,
        "missing_quantity": r.missing_quantity,
        "reason": r.reason,
        "note": r.note,
        "status": r.status,
        "created_at": r.created_at,
        "resolution": r.resolution,
        "resolved_lot_id": r.resolved_lot_id,
        "resolved_lot_number": r.resolved_lot_number,
        "resolution_note": r.resolution_note,
        "resolved_by": r.resolved_by,
        "resolved_at": r.resolved_at,
    }


async def load_discrepancies(
    db: AsyncSession,
    tenant_id: UUID | str,
    transfer_id: UUID | str,
) -> list[TransferDiscrepancyOut]:
    """The discrepancy rows of a transfer, ordered by line then lot."""
    result = await db.execute(
        text(
            f"SELECT {_DISCREPANCY_COLUMNS} "
            "FROM transfer_discrepancies d "
            f"{_DISCREPANCY_LOT_JOINS}"
            "WHERE d.tenant_id = :tid AND d.transfer_order_id = :xfer_id "
            "ORDER BY d.transfer_line_id, d.lot_id"
        ),
        {"tid": str(tenant_id), "xfer_id": str(transfer_id)},
    )
    return [TransferDiscrepancyOut(**_discrepancy_fields(r)) for r in result.fetchall()]


# ── resolution ───────────────────────────────────────────────────────────────

# Outcomes a reason may be resolved with. RECEIVED_AS_LOT additionally needs a
# batch line (the row has a lot_id) — see _allowed_resolutions().
_RESOLUTIONS_BY_REASON: dict[str, tuple[str, ...]] = {
    "SHORT": ("WRITTEN_OFF", "RETURNED", "ARRIVED_LATE"),
    "DAMAGED": ("WRITTEN_OFF",),
    "WRONG_LOT": ("WRITTEN_OFF", "RETURNED", "RECEIVED_AS_LOT"),
}

# Roles that resolve tenant-wide; RM is limited to its node subtree.
_TENANT_WIDE_ROLES = frozenset({"TA", "NM", "SA"})

# Roles scoped to their node subtree (shared with check_permission(); RM included, RB-2 G3).
from shared.permissions.hierarchy_service import FACILITY_SCOPED_ROLES as _FACILITY_SCOPED_ROLES  # noqa: E402
from shared.permissions.hierarchy_service import NO_NODE_TENANT_WIDE_ROLES as _NO_NODE_TENANT_WIDE  # noqa: E402

# Outcomes that move stock at the source, so the source must be in the RM's scope too.
_SOURCE_RESOLUTIONS = frozenset({"RETURNED", "RECEIVED_AS_LOT"})


def _allowed_resolutions(reason: str, lot_id: Optional[Any]) -> list[str]:
    return [
        r
        for r in _RESOLUTIONS_BY_REASON.get(reason, ())
        if r != "RECEIVED_AS_LOT" or lot_id is not None
    ]


def _lot_invalid(lot_id: Optional[UUID]) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={
            "code": "RESOLUTION_LOT_INVALID",
            "lot_id": str(lot_id) if lot_id is not None else None,
        },
    )


async def _load_lot(db: AsyncSession, tenant_id: str, lot_id: Any) -> Any:
    """(id, product_id, lot_number, expiry_date) of a tenant's lot, or None."""
    return (
        await db.execute(
            text(
                "SELECT id, product_id, lot_number, expiry_date FROM stock_lots "
                "WHERE id = :lid AND tenant_id = :tid"
            ),
            {"lid": str(lot_id), "tid": tenant_id},
        )
    ).fetchone()


async def _subtree(db: AsyncSession, tenant_id: str, node_id: Any) -> set[str]:
    """The caller's node and its descendants (get_descendant_node_ids), lowercased."""
    return {str(n).lower() for n in await get_descendant_node_ids(db, tenant_id, str(node_id))}


def _inside(subtree: set[str], nodes: Iterable[Any]) -> bool:
    """Whether every node is in the lowercased subtree — JWT and DB casing differ."""
    return all(str(node).lower() in subtree for node in nodes)


async def _check_scope(
    db: AsyncSession,
    user: Any,
    tenant_id: str,
    resolution: str,
    from_warehouse_id: Any,
    to_warehouse_id: Any,
) -> None:
    """TA / NM / SA resolve tenant-wide. An RM needs the destination — and the
    source, for outcomes that move stock there — inside its node subtree.
    Any other role is refused (defence in depth: the permission blocks them)."""
    role = getattr(user, "role", None)
    if role in _TENANT_WIDE_ROLES:
        return
    out_of_scope = HTTPException(status_code=403, detail={"code": "DISCREPANCY_OUT_OF_SCOPE"})
    if role != "RM" or not getattr(user, "warehouse_id", None):
        raise out_of_scope

    required = [to_warehouse_id]
    if resolution in _SOURCE_RESOLUTIONS:
        required.append(from_warehouse_id)
    if not _inside(await _subtree(db, tenant_id, user.warehouse_id), required):
        raise out_of_scope


async def resolve_discrepancy(
    db: AsyncSession,
    user: Any,
    transfer_id: UUID | str,
    discrepancy_id: UUID | str,
    body: ResolveDiscrepancyRequest,
) -> TransferDiscrepancyOut:
    """Settle one OPEN discrepancy — ledger rows, the OPEN -> RESOLVED UPDATE
    and the audit row, all in the caller's single transaction.

    404 DISCREPANCY_NOT_FOUND         no such row on this transfer for the tenant
    409 DISCREPANCY_ALREADY_RESOLVED  the row is not OPEN (or lost a race)
    403 DISCREPANCY_OUT_OF_SCOPE      RM outside its subtree, or not RM/TA/NM/SA —
                                      checked before the body is validated
    422 RESOLUTION_NOT_ALLOWED        the outcome does not fit the reason
    422 RESOLUTION_NOTE_REQUIRED      WRITTEN_OFF without a note
    422 RESOLUTION_LOT_INVALID        lot_id missing / not allowed / wrong lot
    422 INSUFFICIENT_LOT_STOCK        (record_transaction) the arrived lot lacks
                                      N at the source — nothing is kept
    """
    tenant_id = str(user.tenant_id)
    transfer_id, discrepancy_id = str(transfer_id), str(discrepancy_id)
    resolution = body.resolution
    note = (body.note or "").strip() or None

    # a) the row, locked against a concurrent resolve
    d = (
        await db.execute(
            text(
                "SELECT d.id, d.product_id, d.lot_id, d.missing_quantity, d.reason, "
                "       d.status, t.from_warehouse_id, t.to_warehouse_id "
                "FROM transfer_discrepancies d "
                "JOIN transfer_orders t ON t.id = d.transfer_order_id AND t.tenant_id = d.tenant_id "
                "WHERE d.id = :did AND d.tenant_id = :tid AND d.transfer_order_id = :xfer_id "
                "FOR UPDATE OF d"
            ),
            {"did": discrepancy_id, "tid": tenant_id, "xfer_id": transfer_id},
        )
    ).fetchone()
    if d is None:
        raise HTTPException(status_code=404, detail={"code": "DISCREPANCY_NOT_FOUND"})

    # b) exactly once
    if d.status != "OPEN":
        raise HTTPException(status_code=409, detail={"code": "DISCREPANCY_ALREADY_RESOLVED"})

    # c) scope — before any body validation. The required nodes depend on the
    #    resolution, which the schema has already constrained to a known value.
    await _check_scope(db, user, tenant_id, resolution, d.from_warehouse_id, d.to_warehouse_id)

    # d) the outcome must fit the reason
    allowed = _allowed_resolutions(d.reason, d.lot_id)
    if resolution not in allowed:
        raise HTTPException(
            status_code=422,
            detail={"code": "RESOLUTION_NOT_ALLOWED", "reason": d.reason, "allowed": allowed},
        )

    # e) a write-off says why
    if resolution == "WRITTEN_OFF" and note is None:
        raise HTTPException(status_code=422, detail={"code": "RESOLUTION_NOTE_REQUIRED"})

    # f) the arrived lot: RECEIVED_AS_LOT only, same tenant and product, not the
    #    sent lot. An expired lot is accepted — this records what happened.
    arrived = None
    if resolution != "RECEIVED_AS_LOT":
        if body.lot_id is not None:
            raise _lot_invalid(body.lot_id)
    else:
        if body.lot_id is None or str(body.lot_id).lower() == str(d.lot_id).lower():
            raise _lot_invalid(body.lot_id)
        arrived = await _load_lot(db, tenant_id, body.lot_id)
        if arrived is None or str(arrived.product_id).lower() != str(d.product_id).lower():
            raise _lot_invalid(body.lot_id)

    # g) ledger — record_transaction directly, so a duplicate key (409) or a
    #    lot floor failure (422) aborts the whole resolution.
    sent = await _load_lot(db, tenant_id, d.lot_id) if d.lot_id is not None else None
    n = Decimal(str(d.missing_quantity))
    product_id = str(d.product_id)
    from_wh, to_wh = str(d.from_warehouse_id), str(d.to_warehouse_id)
    key_prefix = f"transfer:{transfer_id}:discrepancy:{discrepancy_id}"

    async def _post(
        transaction_type: str, warehouse_id: str, quantity: Decimal, lot: Any, suffix: str
    ) -> None:
        await record_transaction(
            db,
            tenant_id=tenant_id,
            transaction_type=transaction_type,
            product_id=product_id,
            warehouse_id=warehouse_id,
            quantity=quantity,
            performed_by=str(user.user_id),
            idempotency_key=f"{key_prefix}:{suffix}",
            reference_type="TRANSFER",
            reference_id=transfer_id,
            lot_id=str(lot.id) if lot is not None else None,
            lot_number=lot.lot_number if lot is not None else None,
            expiry_date=lot.expiry_date if lot is not None else None,
        )

    if resolution == "RETURNED":
        await _post("TRANSFER_REVERSAL", from_wh, n, sent, "return")
    elif resolution == "ARRIVED_LATE":
        await _post("TRANSFER_IN", to_wh, n, sent, "late")
    elif resolution == "RECEIVED_AS_LOT":
        # Both source rows lock a lot_balances row at the source. Post them in
        # lot_id order — the order the allocation engine locks lots in
        # (load_candidate_lots: ORDER BY lot_id FOR UPDATE) — so a concurrent
        # allocation can never deadlock against this resolution.
        source_rows = sorted(
            [
                ("TRANSFER_REVERSAL", n, sent, "swap:return"),
                ("TRANSFER_OUT", -n, arrived, "swap:out"),
            ],
            key=lambda row: str(row[2].id).lower(),
        )
        for transaction_type, quantity, lot, suffix in source_rows:
            await _post(transaction_type, from_wh, quantity, lot, suffix)
        await _post("TRANSFER_IN", to_wh, n, arrived, "swap:in")

    # h) OPEN -> RESOLVED, exactly once
    resolved_lot_id = str(arrived.id) if arrived is not None else None
    updated = await db.execute(
        text(
            "UPDATE transfer_discrepancies "
            "SET status = 'RESOLVED', resolution = :resolution, "
            "    resolved_lot_id = :resolved_lot_id, resolution_note = :note, "
            "    resolved_by = :uid, resolved_at = now() "
            "WHERE id = :did AND tenant_id = :tid AND status = 'OPEN'"
        ),
        {
            "resolution": resolution,
            "resolved_lot_id": resolved_lot_id,
            "note": note,
            "uid": str(user.user_id),
            "did": discrepancy_id,
            "tid": tenant_id,
        },
    )
    if updated.rowcount != 1:
        raise HTTPException(status_code=409, detail={"code": "DISCREPANCY_ALREADY_RESOLVED"})

    # i) audit, same transaction (lot_expiry_service pattern)
    await db.execute(
        text(
            "INSERT INTO audit_logs "
            "  (id, tenant_id, user_id, role, action, resource_type, "
            "   resource_id, decision, abac_context) "
            "VALUES "
            "  (:id, :tid, :uid, :role, 'transfer:resolve_discrepancy', 'transfer_discrepancy', "
            "   :rid, 'GRANTED', CAST(:ctx AS jsonb))"
        ),
        {
            "id": str(uuid.uuid4()),
            "tid": tenant_id,
            "uid": str(user.user_id),
            "role": getattr(user, "role", None),
            "rid": discrepancy_id,
            "ctx": json.dumps(
                {
                    "discrepancy_id": discrepancy_id,
                    "transfer_id": transfer_id,
                    "reason": d.reason,
                    "resolution": resolution,
                    "quantity": str(n),
                    "product_id": product_id,
                    "lot_id": str(d.lot_id) if d.lot_id is not None else None,
                    "resolved_lot_id": resolved_lot_id,
                    "from_warehouse_id": from_wh,
                    "to_warehouse_id": to_wh,
                    "note": note,
                }
            ),
        },
    )

    row = (
        await db.execute(
            text(
                f"SELECT {_DISCREPANCY_COLUMNS} "
                "FROM transfer_discrepancies d "
                f"{_DISCREPANCY_LOT_JOINS}"
                "WHERE d.id = :did AND d.tenant_id = :tid"
            ),
            {"did": discrepancy_id, "tid": tenant_id},
        )
    ).fetchone()
    return TransferDiscrepancyOut(**_discrepancy_fields(row))


# ── list ─────────────────────────────────────────────────────────────────────


async def list_discrepancies(
    db: AsyncSession,
    user: Any,
    status: Optional[str] = None,
    warehouse_id: Optional[UUID | str] = None,
) -> list[TransferDiscrepancyListItem]:
    """The tenant's discrepancy rows, newest first, at most 200.

    Scope is the caller's node subtree (get_descendant_node_ids), matched
    against either end of the transfer:
      WM / LM / SA_GT / RT / RM  their subtree; no node -> no rows
      TA / NM / SA / AU          the whole tenant

    warehouse_id narrows to rows where either end equals it. For a
    subtree-scoped caller it must lie inside the subtree, else
    403 WAREHOUSE_OUT_OF_SCOPE.
    """
    tenant_id = str(user.tenant_id)
    role = getattr(user, "role", None)
    node_id = getattr(user, "warehouse_id", None)
    if role in _FACILITY_SCOPED_ROLES and not node_id and role not in _NO_NODE_TENANT_WIDE:
        return []

    params: dict[str, Any] = {"tid": tenant_id}
    filters = ""
    if status is not None:
        filters += " AND d.status = :status"
        params["status"] = status
    if node_id and role in _FACILITY_SCOPED_ROLES:
        subtree = await _subtree(db, tenant_id, node_id)
        if warehouse_id is not None and not _inside(subtree, [warehouse_id]):
            raise HTTPException(status_code=403, detail={"code": "WAREHOUSE_OUT_OF_SCOPE"})
        filters += " AND (t.from_warehouse_id = ANY(:subtree) OR t.to_warehouse_id = ANY(:subtree))"
        params["subtree"] = sorted(subtree)
    if warehouse_id is not None:
        filters += " AND (t.from_warehouse_id = :wh OR t.to_warehouse_id = :wh)"
        params["wh"] = str(warehouse_id).lower()

    result = await db.execute(
        text(
            f"SELECT {_DISCREPANCY_COLUMNS}, d.transfer_order_id, t.transfer_type, "
            "       t.from_warehouse_id, t.to_warehouse_id "
            "FROM transfer_discrepancies d "
            "JOIN transfer_orders t ON t.id = d.transfer_order_id AND t.tenant_id = d.tenant_id "
            f"{_DISCREPANCY_LOT_JOINS}"
            f"WHERE d.tenant_id = :tid{filters} "
            "ORDER BY d.created_at DESC, d.id "
            "LIMIT 200"
        ),
        params,
    )
    return [
        TransferDiscrepancyListItem(
            **_discrepancy_fields(r),
            transfer_order_id=r.transfer_order_id,
            transfer_type=r.transfer_type,
            from_warehouse_id=r.from_warehouse_id,
            to_warehouse_id=r.to_warehouse_id,
        )
        for r in result.fetchall()
    ]
