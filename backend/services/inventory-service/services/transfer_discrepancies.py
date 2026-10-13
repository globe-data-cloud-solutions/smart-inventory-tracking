"""Transfer receipt confirmation — what arrived, and what did not.

The destination confirms a received quantity per allocated lot (batch line) or
per line (non-batch line). A quantity below what was sent becomes one row in
transfer_discrepancies (086); TRANSFER_IN credits the received quantity only.

  validate_receipt     check the whole receipt body against the transfer,
                       before anything is written
  insert_discrepancy   the ONLY write path to transfer_discrepancies
  load_discrepancies   the rows of a transfer, with the lot number

Append-only BY CODE: there is no update or delete function here. Rows are
written with status OPEN; resolution (write-off / return) is a later phase.

PERMISSIONS: not checked here. The router requires transfer:receive and
InventoryService.receive_transfer() runs the destination-warehouse check.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping, Optional, Sequence
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.inventory import ReceiptLineIn, TransferDiscrepancyOut

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
    RECEIPT_REASON_REQUIRED  received less than was sent and no reason given
    """
    keys: list[EntryKey] = [
        (str(e.line_id), str(e.lot_id) if e.lot_id is not None else None)
        for e in receipt_lines
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


async def load_discrepancies(
    db: AsyncSession,
    tenant_id: UUID | str,
    transfer_id: UUID | str,
) -> list[TransferDiscrepancyOut]:
    """The discrepancy rows of a transfer, ordered by line then lot."""
    result = await db.execute(
        text(
            "SELECT d.id, d.transfer_line_id, d.product_id, d.lot_id, sl.lot_number, "
            "       d.sent_quantity, d.received_quantity, d.missing_quantity, "
            "       d.reason, d.note, d.status, d.created_at "
            "FROM transfer_discrepancies d "
            "LEFT JOIN stock_lots sl ON sl.id = d.lot_id AND sl.tenant_id = d.tenant_id "
            "WHERE d.tenant_id = :tid AND d.transfer_order_id = :xfer_id "
            "ORDER BY d.transfer_line_id, d.lot_id"
        ),
        {"tid": str(tenant_id), "xfer_id": str(transfer_id)},
    )
    return [
        TransferDiscrepancyOut(
            id=r.id,
            transfer_line_id=r.transfer_line_id,
            product_id=r.product_id,
            lot_id=r.lot_id,
            lot_number=r.lot_number,
            sent_quantity=r.sent_quantity,
            received_quantity=r.received_quantity,
            missing_quantity=r.missing_quantity,
            reason=r.reason,
            note=r.note,
            status=r.status,
            created_at=r.created_at,
        )
        for r in result.fetchall()
    ]
