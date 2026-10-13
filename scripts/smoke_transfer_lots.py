"""Rollback-only real-DB smoke check for the transfer lot flow
(services/transfer_lots.py + migration 085 transfer_line_allocations).

Opens ONE async session against DATABASE_URL, sets the RLS context for the
permanent zz-e2e-ta tenant, and NEVER commits — everything happens inside one
transaction that is rolled back in a `finally` block, so it is safe to run
against a real database with no cleanup step.

Prints PASS/FAIL per assertion, then "ROLLED BACK". Exits 1 on any FAIL.

Usage:
    set -a; source .env; set +a
    python scripts/smoke_transfer_lots.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import traceback
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

os.environ["FEATURE_LOT_TRACKING"] = "1"

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BACKEND = _REPO_ROOT / "backend"
_INVENTORY_ROOT = _BACKEND / "services" / "inventory-service"
for _p in (str(_BACKEND), str(_INVENTORY_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from sqlalchemy import text  # noqa: E402

from shared.db.session import AsyncSessionLocal  # noqa: E402
from shared.db.rls import set_rls_context  # noqa: E402
from repositories.ledger_repo import record_transaction  # noqa: E402
from repositories.lot_repo import get_or_create_lot, lot_totals_mismatch  # noqa: E402
from services import transfer_lots  # noqa: E402

E2E_TENANT_ID = "5e60ea08-d596-4a46-b63e-ddd7c373f3f0"
E2E_USER_ID = "e05c6e17-1d3c-45f8-9da3-12000b461868"

_failures: list[str] = []


class SmokeStop(Exception):
    """A precondition of the smoke is not met — nothing was tested."""


def _check(cond: bool, label: str) -> None:
    if cond:
        print(f"PASS {label}")
    else:
        print(f"FAIL {label}")
        _failures.append(label)


async def _receive_lot(session, product_id, wh, lot_number, qty) -> str:
    lot_id = await get_or_create_lot(
        session, E2E_TENANT_ID, product_id, lot_number, None, E2E_USER_ID
    )
    await record_transaction(
        session,
        E2E_TENANT_ID,
        "RECEIVE",
        product_id,
        wh,
        qty,
        E2E_USER_ID,
        f"smoke:transfer:receive:{product_id}:{lot_number}:{uuid.uuid4()}",
        lot_id=lot_id,
        lot_number=lot_number,
        source="WEB",
    )
    return lot_id


async def _lot_balances(session, product_id: str, wh: str) -> dict[str, Decimal]:
    rows = (await session.execute(
        text(
            "SELECT lot_id, quantity FROM lot_balances "
            "WHERE tenant_id = :tid AND product_id = :pid AND warehouse_id = :wid"
        ),
        {"tid": E2E_TENANT_ID, "pid": product_id, "wid": wh},
    )).fetchall()
    return {str(r.lot_id): Decimal(str(r.quantity)) for r in rows}


async def _product_balance(session, product_id: str, wh: str) -> Decimal:
    row = (await session.execute(
        text(
            "SELECT quantity FROM inventory_balances "
            "WHERE tenant_id = :tid AND product_id = :pid AND warehouse_id = :wid "
            "AND lot_number IS NULL"
        ),
        {"tid": E2E_TENANT_ID, "pid": product_id, "wid": wh},
    )).fetchone()
    return Decimal(str(row.quantity)) if row else Decimal("0")


async def _row_counts(session, transfer_id: str) -> tuple[int, int]:
    """(transfer_line_allocations rows, ledger rows) for this transfer."""
    allocs = (await session.execute(
        text(
            "SELECT count(*) AS cnt FROM transfer_line_allocations "
            "WHERE tenant_id = :tid AND transfer_order_id = :xfer"
        ),
        {"tid": E2E_TENANT_ID, "xfer": transfer_id},
    )).fetchone().cnt
    ledger = (await session.execute(
        text(
            "SELECT count(*) AS cnt FROM inventory_transactions "
            "WHERE tenant_id = :tid AND reference_id::text = :xfer"
        ),
        {"tid": E2E_TENANT_ID, "xfer": transfer_id},
    )).fetchone().cnt
    return allocs, ledger


async def _lot_identity(session, lot_ids: list[str]) -> dict[str, tuple]:
    rows = (await session.execute(
        text(
            "SELECT id, lot_number, expiry_date, first_received_at FROM stock_lots "
            "WHERE tenant_id = :tid AND id::text = ANY(:ids)"
        ),
        {"tid": E2E_TENANT_ID, "ids": lot_ids},
    )).fetchall()
    return {str(r.id): (r.lot_number, r.expiry_date, r.first_received_at) for r in rows}


async def _add_line(session, transfer_id: str, product_id: str, qty: str) -> SimpleNamespace:
    line_id = str(uuid.uuid4())
    await session.execute(
        text(
            "INSERT INTO transfer_order_lines (id, transfer_order_id, tenant_id, product_id, quantity) "
            "VALUES (:id, :xfer, :tid, :pid, :qty)"
        ),
        {"id": line_id, "xfer": transfer_id, "tid": E2E_TENANT_ID, "pid": product_id, "qty": qty},
    )
    return SimpleNamespace(id=line_id, product_id=product_id, quantity=Decimal(qty))


async def _run(session, suffix: str) -> None:
    await set_rls_context(session, E2E_TENANT_ID, E2E_USER_ID)

    # ── setup: two temporary stock-holding warehouse nodes, a batch FIFO product, two lots ──
    src = str(uuid.uuid4())
    dst = str(uuid.uuid4())
    for node_id, label, code in ((src, "Smoke Transfer Source", f"SMOKE-SRC-{suffix}"),
                                  (dst, "Smoke Transfer Destination", f"SMOKE-DST-{suffix}")):
        await session.execute(
            text(
                "INSERT INTO organization_node "
                "(id, tenant_id, name, code, hierarchy_level, is_stock_holding, is_active) "
                "VALUES (:id, :tid, :name, :code, 1, true, true)"
            ),
            {"id": node_id, "tid": E2E_TENANT_ID, "name": f"{label} {suffix}", "code": code},
        )
    print(f"     source={src}  destination={dst}")

    product_id = str(uuid.uuid4())
    await session.execute(
        text(
            "INSERT INTO products "
            "(id, tenant_id, sku, name, unit_of_measure, batch_tracking, expiry_tracking, "
            " dispatch_strategy, is_active) "
            "VALUES (:id, :tid, :sku, :name, 'EACH', true, false, "
            "        CAST('FIFO' AS dispatch_strategy), true)"
        ),
        {
            "id": product_id,
            "tid": E2E_TENANT_ID,
            "sku": f"SMKT-{suffix}",
            "name": f"Smoke Transfer Product {suffix}",
        },
    )
    lot_a = await _receive_lot(session, product_id, src, "LOT-A", Decimal("60"))
    lot_b = await _receive_lot(session, product_id, src, "LOT-B", Decimal("80"))

    # stock_lots.first_received_at defaults to now(), the TRANSACTION start time,
    # so both lots would share one timestamp. Space them out: LOT-A is the older.
    for lot_id, hours_ago in ((lot_a, 2), (lot_b, 1)):
        await session.execute(
            text(
                "UPDATE stock_lots SET first_received_at = now() - make_interval(hours => :h) "
                "WHERE id = :lid AND tenant_id = :tid"
            ),
            {"h": hours_ago, "lid": lot_id, "tid": E2E_TENANT_ID},
        )
    identity_before = await _lot_identity(session, [lot_a, lot_b])

    transfer_id = str(uuid.uuid4())
    await session.execute(
        text(
            "INSERT INTO transfer_orders "
            "(id, tenant_id, from_warehouse_id, to_warehouse_id, transfer_type, status, created_by) "
            "VALUES (:id, :tid, :src, :dst, 'PUSH', 'PENDING_APPROVAL', :uid)"
        ),
        {"id": transfer_id, "tid": E2E_TENANT_ID, "src": src, "dst": dst, "uid": E2E_USER_ID},
    )
    line = await _add_line(session, transfer_id, product_id, "100")
    key_prefix = f"transfer:{transfer_id}:approve:out"
    balance_before = await _product_balance(session, product_id, src)
    _check(balance_before == Decimal("140"), f"setup: source holds LOT-A 60 + LOT-B 80 (balance {balance_before})")

    async def _post_out(lines) -> None:
        await transfer_lots.post_transfer_out(
            session,
            tenant_id=E2E_TENANT_ID,
            user_id=E2E_USER_ID,
            transfer_id=transfer_id,
            from_warehouse_id=src,
            lines=lines,
            key_prefix=key_prefix,
        )

    # ── 1) post_transfer_out: FIFO takes LOT-A 60 then LOT-B 40 ──
    await _post_out([line])
    allocs = (await transfer_lots.load_allocations(session, E2E_TENANT_ID, transfer_id))[line.id]
    got = {a.lot_number: a.quantity for a in allocs}
    print(f"     allocations: {[(a.lot_number, str(a.quantity)) for a in allocs]}")
    _check(got == {"LOT-A": Decimal("60"), "LOT-B": Decimal("40")},
           "1) allocations are LOT-A 60, LOT-B 40")
    src_lots = await _lot_balances(session, product_id, src)
    _check(src_lots == {lot_a: Decimal("0"), lot_b: Decimal("40")},
           f"1) source lot balances are 0 and 40 (got {sorted(str(v) for v in src_lots.values())})")
    balance_after = await _product_balance(session, product_id, src)
    _check(balance_after - balance_before == Decimal("-100"),
           f"1) source product balance moved by -100 ({balance_before} -> {balance_after})")

    # ── 2) replay with the same key_prefix: nothing new ──
    counts_before = await _row_counts(session, transfer_id)
    await _post_out([line])
    counts_after = await _row_counts(session, transfer_id)
    print(f"     (allocation rows, ledger rows) before={counts_before} after={counts_after}")
    _check(counts_after == counts_before == (2, 2), "2) replay writes no new allocation or ledger rows")
    _check(await _lot_balances(session, product_id, src) == src_lots,
           "2) replay leaves the source lot balances unchanged")
    _check(await _product_balance(session, product_id, src) == balance_after,
           "2) replay leaves the source product balance unchanged")

    # ── 3) post_transfer_in: destination is credited on the SAME lot_ids ──
    await transfer_lots.post_transfer_in(
        session,
        tenant_id=E2E_TENANT_ID,
        user_id=E2E_USER_ID,
        transfer_id=transfer_id,
        to_warehouse_id=dst,
        line=line,
        allocs=allocs,
    )
    dst_lots = await _lot_balances(session, product_id, dst)
    _check(dst_lots == {lot_a: Decimal("60"), lot_b: Decimal("40")},
           "3) destination lot_balances are LOT-A 60, LOT-B 40 on the same lot_ids")
    _check(await _product_balance(session, product_id, dst) == Decimal("100"),
           "3) destination product balance is 100")
    identity_after = await _lot_identity(session, [lot_a, lot_b])
    _check(identity_after == identity_before,
           "3) stock_lots lot_number, expiry_date and first_received_at are unchanged")

    # ── 4) lot totals agree with the product totals at both warehouses ──
    for label, wh in (("source", src), ("destination", dst)):
        mismatch = await lot_totals_mismatch(session, E2E_TENANT_ID, product_id, wh)
        _check(mismatch is None, f"4) lot_totals_mismatch at {label} returns nothing (got {mismatch})")

    # ── second scenario: a new line is posted out, then reversed per lot ──
    line2 = await _add_line(session, transfer_id, product_id, "30")
    pre_lots = await _lot_balances(session, product_id, src)
    pre_balance = await _product_balance(session, product_id, src)

    await _post_out([line2])
    allocs2 = (await transfer_lots.load_allocations(session, E2E_TENANT_ID, transfer_id))[line2.id]
    print(f"     line 2 allocations: {[(a.lot_number, str(a.quantity)) for a in allocs2]}")
    _check([(a.lot_number, a.quantity) for a in allocs2] == [("LOT-B", Decimal("30"))],
           "5) line 2 (30) is allocated from LOT-B — LOT-A is already empty")
    mid_lots = await _lot_balances(session, product_id, src)
    _check(mid_lots == {lot_a: Decimal("0"), lot_b: Decimal("10")},
           "5) source lot balances after line 2 are 0 and 10")

    await transfer_lots.post_lot_audit(
        session,
        tenant_id=E2E_TENANT_ID,
        user_id=E2E_USER_ID,
        transfer_id=transfer_id,
        line=line2,
        allocs=allocs2,
        transaction_type="TRANSFER_REVERSAL",
        warehouse_id=src,
        sign=1,
        status_transition="APPROVED_TO_CANCELLED",
    )
    _check(await _lot_balances(session, product_id, src) == pre_lots,
           "5) TRANSFER_REVERSAL puts the source lot balances back to their pre-transfer values")
    _check(await _product_balance(session, product_id, src) == pre_balance,
           "5) TRANSFER_REVERSAL restores the source product balance")
    mismatch = await lot_totals_mismatch(session, E2E_TENANT_ID, product_id, src)
    _check(mismatch is None, f"5) lot_totals_mismatch at source returns nothing (got {mismatch})")


async def main() -> int:
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        try:
            await _run(session, suffix)
        except SmokeStop as stop:
            print(f"STOP {stop}")
            _failures.append("precondition not met")
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
        product = (await verify_session.execute(
            text("SELECT id FROM products WHERE tenant_id = :tid AND sku = :sku"),
            {"tid": E2E_TENANT_ID, "sku": f"SMKT-{suffix}"},
        )).fetchone()
        allocations = (await verify_session.execute(
            text(
                "SELECT count(*) AS cnt FROM transfer_line_allocations a "
                "JOIN products p ON p.id = a.product_id "
                "WHERE a.tenant_id = :tid AND p.sku = :sku"
            ),
            {"tid": E2E_TENANT_ID, "sku": f"SMKT-{suffix}"},
        )).fetchone()
        await verify_session.rollback()
    _check(product is None, "6) post-rollback: smoke product not found")
    _check(allocations.cnt == 0, f"6) post-rollback: smoke allocation rows = {allocations.cnt}")

    if _failures:
        print(f"SMOKE FAIL ({len(_failures)} failed)")
        return 1
    print("SMOKE PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
