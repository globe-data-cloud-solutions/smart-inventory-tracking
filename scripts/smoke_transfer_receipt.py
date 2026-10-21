"""Rollback-only real-DB smoke check for transfer receipt confirmation
(InventoryService.receive_transfer() + services/transfer_discrepancies.py +
migration 086 transfer_discrepancies).

Same approach as smoke_transfer_lots.py (its helpers are imported): ONE async
session against DATABASE_URL, RLS context for the permanent zz-e2e-ta tenant,
temporary nodes in organization_node, service methods called directly, and
NEVER a commit — everything is rolled back in a `finally` block.

audit_log() opens its own session and commits, so it is replaced with a no-op
for this run — otherwise the approve/dispatch steps would leave audit rows.

Prints PASS/FAIL per assertion, then "ROLLED BACK". Exits 1 on any FAIL.

Usage:
    set -a; source .env; set +a
    python scripts/smoke_transfer_receipt.py
"""

from __future__ import annotations

import asyncio
import sys
import traceback
import uuid
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Optional

# Importing the template sets FEATURE_LOT_TRACKING and the backend sys.path.
from smoke_transfer_lots import (  # noqa: E402
    E2E_TENANT_ID,
    E2E_USER_ID,
    _add_line,
    _check,
    _failures,
    _lot_balances,
    _lot_identity,
    _product_balance,
)

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import text  # noqa: E402

from shared.db.session import AsyncSessionLocal  # noqa: E402
from shared.db.rls import set_rls_context  # noqa: E402
from repositories.ledger_repo import record_transaction  # noqa: E402
from repositories.lot_repo import get_or_create_lot  # noqa: E402
from schemas.inventory import ReceiptLineIn, ReceiveTransferRequest  # noqa: E402
from services import inventory_service as inventory_service_module  # noqa: E402
from services.inventory_analytics import get_stock  # noqa: E402
from services.inventory_service import InventoryService  # noqa: E402


async def _no_audit(*args: Any, **kwargs: Any) -> None:
    return None


inventory_service_module.audit_log = _no_audit

# Tenant-level actor: may approve, dispatch and receive at any facility.
USER = SimpleNamespace(
    tenant_id=E2E_TENANT_ID,
    user_id=E2E_USER_ID,
    role="TA",
    warehouse_id=None,
    level_number=None,
)
# transfer_orders.created_by — must differ from the approver (CANNOT_APPROVE_OWN_TRANSFER).
CREATOR_ID = str(uuid.uuid4())


def _d(value: str) -> Decimal:
    return Decimal(value)


async def _make_product(session, suffix: str, tag: str, batch: bool) -> str:
    product_id = str(uuid.uuid4())
    await session.execute(
        text(
            "INSERT INTO products "
            "(id, tenant_id, sku, name, unit_of_measure, batch_tracking, expiry_tracking, "
            " dispatch_strategy, is_active) "
            "VALUES (:id, :tid, :sku, :name, 'EACH', :batch, :batch, "
            "        CAST(:strategy AS dispatch_strategy), true)"
        ),
        {
            "id": product_id,
            "tid": E2E_TENANT_ID,
            "sku": f"SMKR-{tag}-{suffix}",
            "name": f"Smoke Receipt Product {tag} {suffix}",
            "batch": batch,
            "strategy": "FEFO" if batch else "FIFO",
        },
    )
    return product_id


async def _stock(
    session,
    product_id: str,
    wh: str,
    qty: str,
    lot_number: Optional[str] = None,
    expiry_in_days: Optional[int] = None,
) -> Optional[str]:
    """RECEIVE qty at wh; returns the lot_id for a lot receipt."""
    lot_id = None
    expiry = None
    if lot_number is not None:
        expiry = date.today() + timedelta(days=expiry_in_days or 30)
        lot_id = await get_or_create_lot(
            session, E2E_TENANT_ID, product_id, lot_number, expiry, E2E_USER_ID
        )
    await record_transaction(
        session,
        E2E_TENANT_ID,
        "RECEIVE",
        product_id,
        wh,
        _d(qty),
        E2E_USER_ID,
        f"smoke:receipt:receive:{product_id}:{lot_number}:{uuid.uuid4()}",
        lot_id=lot_id,
        lot_number=lot_number,
        expiry_date=expiry,
        source="WEB",
    )
    return lot_id


async def _in_transit_transfer(
    session, svc, src: str, dst: str, product_id: str, qty: str
):
    """A PUSH transfer of qty, approved in engine order and dispatched to IN_TRANSIT."""
    transfer_id = str(uuid.uuid4())
    await session.execute(
        text(
            "INSERT INTO transfer_orders "
            "(id, tenant_id, from_warehouse_id, to_warehouse_id, transfer_type, status, created_by) "
            "VALUES (:id, :tid, :src, :dst, 'PUSH', 'PENDING_APPROVAL', :uid)"
        ),
        {
            "id": transfer_id,
            "tid": E2E_TENANT_ID,
            "src": src,
            "dst": dst,
            "uid": CREATOR_ID,
        },
    )
    line = await _add_line(session, transfer_id, product_id, qty)
    await svc.transition_transfer(USER, uuid.UUID(transfer_id), "APPROVED")
    await svc.dispatch_transfer(USER, uuid.UUID(transfer_id))
    await svc.transition_transfer(USER, uuid.UUID(transfer_id), "IN_TRANSIT")
    return transfer_id, line


async def _status(session, transfer_id: str) -> str:
    return (
        await session.execute(
            text(
                "SELECT status FROM transfer_orders WHERE id = :id AND tenant_id = :tid"
            ),
            {"id": transfer_id, "tid": E2E_TENANT_ID},
        )
    ).scalar()


async def _ledger(session, transfer_id: str, tx_type: str) -> list:
    return (
        await session.execute(
            text(
                "SELECT warehouse_id, lot_id, quantity, idempotency_key FROM inventory_transactions "
                "WHERE tenant_id = :tid AND reference_id::text = :xfer "
                "AND type = CAST(:type AS transaction_type)"
            ),
            {"tid": E2E_TENANT_ID, "xfer": transfer_id, "type": tx_type},
        )
    ).fetchall()


async def _discrepancies(session, transfer_id: str) -> list:
    return (
        await session.execute(
            text(
                "SELECT lot_id, sent_quantity, received_quantity, missing_quantity, "
                "       reason, note, status "
                "FROM transfer_discrepancies WHERE tenant_id = :tid AND transfer_order_id = :xfer"
            ),
            {"tid": E2E_TENANT_ID, "xfer": transfer_id},
        )
    ).fetchall()


async def _write_counts(session, transfer_id: str) -> tuple[int, int]:
    """(inventory_transactions rows, transfer_discrepancies rows) for this transfer."""
    ledger = (
        await session.execute(
            text(
                "SELECT count(*) FROM inventory_transactions "
                "WHERE tenant_id = :tid AND reference_id::text = :xfer"
            ),
            {"tid": E2E_TENANT_ID, "xfer": transfer_id},
        )
    ).scalar()
    return ledger, len(await _discrepancies(session, transfer_id))


async def _in_transit_in(session, product_id: str, wh: str) -> Optional[Decimal]:
    """in_transit_in_qty from the analytics query; None when the warehouse has no stock row."""
    rows = await get_stock(session, uuid.UUID(E2E_TENANT_ID), uuid.UUID(wh))
    for r in rows:
        if str(r.product_id) == product_id:
            return r.in_transit_in_qty
    return None


def _body(*entries: tuple) -> ReceiveTransferRequest:
    """entries: (line_id, lot_id, received[, reason[, note]])."""
    lines = []
    for line_id, lot_id, received, *rest in entries:
        lines.append(
            ReceiptLineIn(
                line_id=line_id,
                lot_id=lot_id,
                received_quantity=_d(received),
                reason=rest[0] if rest else None,
                note=rest[1] if len(rest) > 1 else None,
            )
        )
    return ReceiveTransferRequest(lines=lines)


async def _scenario_a(session, svc, src, dst, suffix) -> None:
    product_id = await _make_product(session, suffix, "A", batch=True)
    lot_a = await _stock(session, product_id, src, "30", "LOT-A", 30)
    lot_b = await _stock(session, product_id, src, "40", "LOT-B", 60)
    identity_before = await _lot_identity(session, [lot_a, lot_b])

    # get_stock() lists a warehouse only once it has an inventory_balances row for
    # the product, and TRANSIT_IN is balance-neutral. Give the destination a
    # zero balance row first (receive 5 of another lot, issue it again) so the
    # in-transit figure is visible before the receipt.
    lot_z = await _stock(session, product_id, dst, "5", "LOT-Z", 90)
    await record_transaction(
        session,
        E2E_TENANT_ID,
        "ISSUE",
        product_id,
        dst,
        _d("-5"),
        E2E_USER_ID,
        f"smoke:receipt:issue:{product_id}:{uuid.uuid4()}",
        lot_id=lot_z,
        lot_number="LOT-Z",
    )
    dst_seed = await _product_balance(session, product_id, dst)
    _check(
        dst_seed == _d("0"),
        f"A) setup: destination holds a zero balance row (got {dst_seed})",
    )

    transfer_id, line = await _in_transit_transfer(
        session, svc, src, dst, product_id, "70"
    )
    src_balance_approved = await _product_balance(session, product_id, src)
    src_lots_approved = await _lot_balances(session, product_id, src)
    _check(
        src_lots_approved == {lot_a: _d("0"), lot_b: _d("0")},
        f"A) after approval the source lots are LOT-A 0, LOT-B 0 "
        f"(got {sorted(str(v) for v in src_lots_approved.values())}, product {src_balance_approved})",
    )

    before = await _in_transit_in(session, product_id, dst)
    _check(
        before == _d("70"),
        f"A) before receipt in_transit_in at the destination = 70 (got {before})",
    )

    await svc.receive_transfer(
        USER,
        uuid.UUID(transfer_id),
        _body(
            (line.id, lot_a, "30"), (line.id, lot_b, "38", "SHORT", "2 cartons missing")
        ),
    )

    dst_lots = await _lot_balances(session, product_id, dst)
    _check(
        dst_lots == {lot_a: _d("30"), lot_b: _d("38"), lot_z: _d("0")},
        f"A) destination lot_balances are LOT-A 30, LOT-B 38 on the source lot_ids "
        f"(got {[str(dst_lots.get(l)) for l in (lot_a, lot_b)]})",
    )
    _check(
        await _lot_identity(session, [lot_a, lot_b]) == identity_before,
        "A) stock_lots lot_number, expiry_date and first_received_at are unchanged",
    )
    dst_balance = await _product_balance(session, product_id, dst)
    _check(
        dst_balance == _d("68"),
        f"A) destination product balance = 68 (got {dst_balance})",
    )

    src_lots = await _lot_balances(session, product_id, src)
    src_balance = await _product_balance(session, product_id, src)
    _check(
        src_lots == src_lots_approved and src_balance == src_balance_approved,
        f"A) source unchanged by the receipt (lots {sorted(str(v) for v in src_lots.values())}, "
        f"product {src_balance_approved} -> {src_balance})",
    )

    ins = await _ledger(session, transfer_id, "TRANSFER_IN")
    got_in = {str(r.lot_id): r.quantity for r in ins}
    _check(
        len(ins) == 2 and got_in == {lot_a: _d("30"), lot_b: _d("38")},
        f"A) exactly one TRANSFER_IN per lot, 30 and 38 (got {sorted(str(r.quantity) for r in ins)})",
    )
    _check(
        all(r.idempotency_key.endswith(f":line:{line.id}:lot:{r.lot_id}") for r in ins),
        f"A) TRANSFER_IN keys end :line:<id>:lot:<lot_id> ({[r.idempotency_key[-20:] for r in ins]})",
    )

    clears = await _ledger(session, transfer_id, "TRANSIT_CLEAR")
    by_wh = {
        wh: {
            str(r.lot_id): abs(r.quantity) for r in clears if str(r.warehouse_id) == wh
        }
        for wh in (src, dst)
    }
    full = {lot_a: _d("30"), lot_b: _d("40")}
    _check(
        len(clears) == 4 and by_wh[src] == full and by_wh[dst] == full,
        f"A) TRANSIT_CLEAR carries the full sent 30 and 40 at source and destination "
        f"(got {sorted(str(r.quantity) for r in clears)})",
    )

    disc = await _discrepancies(session, transfer_id)
    print(
        f"     discrepancies: {[(str(d.sent_quantity), str(d.received_quantity), str(d.missing_quantity), d.reason, d.status, d.note) for d in disc]}"
    )
    _check(len(disc) == 1, f"A) one transfer_discrepancies row (got {len(disc)})")
    if len(disc) == 1:
        d = disc[0]
        _check(
            str(d.lot_id) == lot_b
            and d.sent_quantity == 40
            and d.received_quantity == 38
            and d.missing_quantity == 2
            and d.reason == "SHORT"
            and d.status == "OPEN"
            and d.note == "2 cartons missing",
            "A) discrepancy: lot LOT-B, sent 40, received 38, missing 2, SHORT, OPEN, note saved",
        )

    status = await _status(session, transfer_id)
    _check(status == "RECEIVED", f"A) status = RECEIVED (got {status})")
    after = await _in_transit_in(session, product_id, dst)
    _check(
        after == _d("0"),
        f"A) after receipt in_transit_in at the destination = 0 (got {after})",
    )

    fetched = await svc.get_transfer(USER, uuid.UUID(transfer_id))
    lot_numbers = [d.lot_number for d in fetched.discrepancies]
    _check(
        lot_numbers == ["LOT-B"],
        f"A) get_transfer() returns the discrepancy with lot_number {lot_numbers}",
    )


async def _scenario_b(session, svc, src, dst, suffix) -> None:
    product_id = await _make_product(session, suffix, "B", batch=False)
    await _stock(session, product_id, src, "50")
    transfer_id, line = await _in_transit_transfer(
        session, svc, src, dst, product_id, "50"
    )
    dst_before = await _product_balance(session, product_id, dst)

    await svc.receive_transfer(
        USER,
        uuid.UUID(transfer_id),
        _body((line.id, None, "45", "DAMAGED")),
    )
    dst_after = await _product_balance(session, product_id, dst)
    _check(
        dst_after - dst_before == _d("45"),
        f"B) non-batch: destination +45 only ({dst_before} -> {dst_after})",
    )
    disc = await _discrepancies(session, transfer_id)
    _check(
        len(disc) == 1
        and disc[0].lot_id is None
        and disc[0].missing_quantity == 5
        and disc[0].reason == "DAMAGED",
        f"B) one discrepancy with lot_id NULL, missing 5, DAMAGED "
        f"(got {[(d.lot_id, str(d.missing_quantity), d.reason) for d in disc]})",
    )
    status = await _status(session, transfer_id)
    _check(status == "RECEIVED", f"B) status = RECEIVED (got {status})")


async def _scenario_c(session, svc, src, dst, suffix) -> None:
    product_id = await _make_product(session, suffix, "C", batch=True)
    lot = await _stock(session, product_id, src, "20", "LOT-C", 30)
    transfer_id, line = await _in_transit_transfer(
        session, svc, src, dst, product_id, "20"
    )

    await svc.receive_transfer(
        USER,
        uuid.UUID(transfer_id),
        _body((line.id, lot, "0", "WRONG_LOT")),
    )
    ins = await _ledger(session, transfer_id, "TRANSFER_IN")
    _check(
        len(ins) == 0, f"C) received 0: no TRANSFER_IN row for the lot (got {len(ins)})"
    )
    disc = await _discrepancies(session, transfer_id)
    _check(
        len(disc) == 1
        and str(disc[0].lot_id) == lot
        and disc[0].missing_quantity == 20
        and disc[0].reason == "WRONG_LOT",
        f"C) the discrepancy has missing 20, WRONG_LOT "
        f"(got {[(str(d.missing_quantity), d.reason) for d in disc]})",
    )
    dst_lot = (await _lot_balances(session, product_id, dst)).get(lot)
    _check(
        dst_lot is None or dst_lot == 0,
        f"C) destination balance for the lot is absent or 0 (got {dst_lot})",
    )
    status = await _status(session, transfer_id)
    _check(status == "RECEIVED", f"C) status = RECEIVED (got {status})")


async def _scenario_d(session, svc, src, dst, suffix) -> None:
    product_id = await _make_product(session, suffix, "D", batch=True)
    lot_1 = await _stock(session, product_id, src, "15", "LOT-D1", 30)
    lot_2 = await _stock(session, product_id, src, "25", "LOT-D2", 60)
    transfer_id, _line = await _in_transit_transfer(
        session, svc, src, dst, product_id, "40"
    )

    await svc.receive_transfer(USER, uuid.UUID(transfer_id))
    dst_lots = await _lot_balances(session, product_id, dst)
    dst_balance = await _product_balance(session, product_id, dst)
    _check(
        dst_lots == {lot_1: _d("15"), lot_2: _d("25")} and dst_balance == _d("40"),
        f"D) no body: full quantities credited (lots {sorted(str(v) for v in dst_lots.values())}, "
        f"product {dst_balance})",
    )
    disc = await _discrepancies(session, transfer_id)
    _check(len(disc) == 0, f"D) no body: zero discrepancies (got {len(disc)})")
    status = await _status(session, transfer_id)
    _check(status == "RECEIVED", f"D) status = RECEIVED (got {status})")


async def _scenario_e(session, svc, src, dst, suffix) -> None:
    product_id = await _make_product(session, suffix, "E", batch=True)
    lot_1 = await _stock(session, product_id, src, "10", "LOT-E1", 30)
    lot_2 = await _stock(session, product_id, src, "10", "LOT-E2", 60)
    transfer_id, line = await _in_transit_transfer(
        session, svc, src, dst, product_id, "20"
    )

    cases = (
        (
            "received > sent",
            "RECEIPT_EXCEEDS_SENT",
            _body((line.id, lot_1, "11"), (line.id, lot_2, "10")),
        ),
        (
            "a lot missing from the body",
            "RECEIPT_LINES_MISMATCH",
            _body((line.id, lot_1, "10")),
        ),
        (
            "a short line with no reason",
            "RECEIPT_REASON_REQUIRED",
            _body((line.id, lot_1, "9"), (line.id, lot_2, "10")),
        ),
    )
    for label, expected_code, body in cases:
        counts_before = await _write_counts(session, transfer_id)
        got = "no error"
        savepoint = await session.begin_nested()
        try:
            await svc.receive_transfer(USER, uuid.UUID(transfer_id), body)
        except HTTPException as exc:
            code = (
                exc.detail.get("code") if isinstance(exc.detail, dict) else exc.detail
            )
            got = f"{exc.status_code} {code}"
        # Counted INSIDE the savepoint, before it is rolled back: proves the
        # rejection itself wrote nothing.
        counts_after = await _write_counts(session, transfer_id)
        status_inside = await _status(session, transfer_id)
        await savepoint.rollback()
        _check(
            got == f"422 {expected_code}",
            f"E) {label}: 422 {expected_code} (got {got})",
        )
        _check(
            counts_after == counts_before,
            f"E) {label}: (ledger, discrepancy) counts unchanged {counts_before} -> {counts_after}",
        )
        status = await _status(session, transfer_id)
        _check(
            status_inside == "IN_TRANSIT" and status == "IN_TRANSIT",
            f"E) {label}: status still IN_TRANSIT (got {status})",
        )


async def _run(session, suffix: str) -> None:
    await set_rls_context(session, E2E_TENANT_ID, E2E_USER_ID)

    src = str(uuid.uuid4())
    dst = str(uuid.uuid4())
    for node_id, label, code in (
        (src, "Smoke Receipt Source", f"SMOKE-RSRC-{suffix}"),
        (dst, "Smoke Receipt Destination", f"SMOKE-RDST-{suffix}"),
    ):
        await session.execute(
            text(
                "INSERT INTO organization_node "
                "(id, tenant_id, name, code, hierarchy_level, is_stock_holding, is_active) "
                "VALUES (:id, :tid, :name, :code, 1, true, true)"
            ),
            {
                "id": node_id,
                "tid": E2E_TENANT_ID,
                "name": f"{label} {suffix}",
                "code": code,
            },
        )
    print(f"     source={src}  destination={dst}")

    svc = InventoryService(session)
    for scenario in (_scenario_a, _scenario_b, _scenario_c, _scenario_d, _scenario_e):
        await scenario(session, svc, src, dst, suffix)


async def main() -> int:
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        try:
            await _run(session, suffix)
        except Exception:
            traceback.print_exc()
            print("FAIL unexpected exception (see traceback above)")
            _failures.append("unexpected exception")
        finally:
            # ── never commit ──
            await session.rollback()
            print("ROLLED BACK")

    # ── post-rollback check from a NEW session ──
    async with AsyncSessionLocal() as verify_session:
        await set_rls_context(verify_session, E2E_TENANT_ID, E2E_USER_ID)
        products = (
            await verify_session.execute(
                text(
                    "SELECT count(*) FROM products WHERE tenant_id = :tid AND sku LIKE :sku"
                ),
                {"tid": E2E_TENANT_ID, "sku": f"SMKR-%-{suffix}"},
            )
        ).scalar()
        discrepancies = (
            await verify_session.execute(
                text(
                    "SELECT count(*) FROM transfer_discrepancies d "
                    "JOIN products p ON p.id = d.product_id "
                    "WHERE d.tenant_id = :tid AND p.sku LIKE :sku"
                ),
                {"tid": E2E_TENANT_ID, "sku": f"SMKR-%-{suffix}"},
            )
        ).scalar()
        await verify_session.rollback()
    _check(products == 0, f"post-rollback: smoke products = {products}")
    _check(
        discrepancies == 0, f"post-rollback: smoke discrepancy rows = {discrepancies}"
    )

    if _failures:
        print(f"SMOKE FAIL ({len(_failures)} failed)")
        return 1
    print("SMOKE PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
