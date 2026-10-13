"""Rollback-only real-DB smoke check for the dispatch engine
(services/dispatch_service.py + migration 083 lot_allocation_overrides).

Opens ONE async session against DATABASE_URL, sets the RLS context for the
permanent zz-e2e-ta tenant, and NEVER commits — everything happens inside one
transaction that is rolled back in a `finally` block, so it is safe to run
against a real database with no cleanup step.

Prints PASS/FAIL per assertion, then "ROLLED BACK". Exits 1 on any FAIL.

Usage:
    set -a; source .env; set +a
    python scripts/smoke_dispatch_engine.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import traceback
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

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
from repositories.lot_repo import get_or_create_lot  # noqa: E402
from services.dispatch_service import (  # noqa: E402
    DispatchError,
    InsufficientStockError,
    allocate,
    load_candidate_lots,
    load_product,
    plan_allocation,
    record_override,
    resolve_strategy,
    validate_manual_selection,
)
from services.lot_settings_service import update_lot_settings  # noqa: E402

E2E_TENANT_ID = "5e60ea08-d596-4a46-b63e-ddd7c373f3f0"
E2E_USER_ID = "e05c6e17-1d3c-45f8-9da3-12000b461868"

_failures: list[str] = []


def _check(cond: bool, label: str) -> None:
    if cond:
        print(f"PASS {label}")
    else:
        print(f"FAIL {label}")
        _failures.append(label)


async def _set_lot_settings(session, product_id: str, expiry: bool, strategy):
    return await update_lot_settings(
        session,
        tenant_id=E2E_TENANT_ID,
        product_id=product_id,
        user_id=E2E_USER_ID,
        role="TA",
        feature_enabled=True,
        batch_tracking=True,
        expiry_tracking=expiry,
        dispatch_strategy=strategy,
    )


async def _receive_lot(session, product_id, wh, lot_number, expiry, qty) -> str:
    lot_id = await get_or_create_lot(
        session, E2E_TENANT_ID, product_id, lot_number, expiry, E2E_USER_ID
    )
    await record_transaction(
        session,
        E2E_TENANT_ID,
        "RECEIVE",
        product_id,
        wh,
        qty,
        E2E_USER_ID,
        f"smoke:dispatch:receive:{product_id}:{lot_number}:{uuid.uuid4()}",
        lot_id=lot_id,
        lot_number=lot_number,
        expiry_date=expiry,
        source="WEB",
    )
    return lot_id


async def _resolve(session, product_id):
    product = await load_product(session, E2E_TENANT_ID, product_id)
    return resolve_strategy(
        product.batch_tracking, product.expiry_tracking, product.dispatch_strategy
    )


async def _override_count(session, product_id: str) -> int:
    row = (await session.execute(
        text(
            "SELECT count(*) AS cnt FROM lot_allocation_overrides "
            "WHERE tenant_id = :tid AND product_id = :pid"
        ),
        {"tid": E2E_TENANT_ID, "pid": product_id},
    )).fetchone()
    return row.cnt


async def _run(session, suffix: str) -> None:
    today = date.today()
    await set_rls_context(session, E2E_TENANT_ID, E2E_USER_ID)

    # ── a) a product with stock in one warehouse, then the batch-on conversion ──
    wh = str(uuid.uuid4())
    await session.execute(
        text(
            "INSERT INTO warehouses (id, tenant_id, name, code, is_active) "
            "VALUES (:id, :tid, :name, :code, true)"
        ),
        {"id": wh, "tid": E2E_TENANT_ID, "name": f"Smoke Dispatch WH {suffix}", "code": f"SMKD{suffix}"},
    )
    product_id = str(uuid.uuid4())
    await session.execute(
        text(
            "INSERT INTO products "
            "(id, tenant_id, sku, name, unit_of_measure, batch_tracking, expiry_tracking, is_active) "
            "VALUES (:id, :tid, :sku, :name, 'EACH', false, false, true)"
        ),
        {
            "id": product_id,
            "tid": E2E_TENANT_ID,
            "sku": f"SMKD-{suffix}",
            "name": f"Smoke Dispatch Product {suffix}",
        },
    )
    await record_transaction(
        session,
        E2E_TENANT_ID,
        "RECEIVE",
        product_id,
        wh,
        Decimal("10"),
        E2E_USER_ID,
        f"smoke:dispatch:receive:{product_id}:{uuid.uuid4()}",
        source="OPENING_BALANCE",
    )
    _check(await _resolve(session, product_id) == (None, "NOT_BATCH"),
           "a) non-batch product resolves to (None, NOT_BATCH)")

    converted = await _set_lot_settings(session, product_id, expiry=False, strategy=None)
    _check(len(converted.opening_lots) == 1, "a) conversion created one OPENING lot")
    opening = converted.opening_lots[0]
    opening_id = str(opening.lot_id)
    print(f"     OPENING lot {opening.lot_number} qty={opening.quantity}")
    resolved = await _resolve(session, product_id)
    _check(resolved == ("FIFO", "PRODUCT"), f"a) batch-on product resolves to (FIFO, PRODUCT) (got {resolved})")

    # ── b) L1 (expiry +90), then L2 (expiry +30, received AFTER L1), L3 expired ──
    l1 = await _receive_lot(session, product_id, wh, "SMK-L1", today + timedelta(days=90), Decimal("8"))
    l2 = await _receive_lot(session, product_id, wh, "SMK-L2", today + timedelta(days=30), Decimal("6"))
    l3 = await _receive_lot(session, product_id, wh, "SMK-L3", today - timedelta(days=1), Decimal("5"))

    # stock_lots.first_received_at defaults to now(), which is the TRANSACTION
    # start time — every lot created in this single transaction would share one
    # timestamp. Real receipts are separate transactions, so space them out here
    # to reproduce the real order: OPENING, then L1, then L2, then L3.
    for lot_id, hours_ago in ((opening_id, 4), (l1, 3), (l2, 2), (l3, 1)):
        await session.execute(
            text(
                "UPDATE stock_lots SET first_received_at = now() - make_interval(hours => :h) "
                "WHERE id = :lid AND tenant_id = :tid"
            ),
            {"h": hours_ago, "lid": lot_id, "tid": E2E_TENANT_ID},
        )

    lots = await load_candidate_lots(session, E2E_TENANT_ID, product_id, wh)
    print(f"     candidate lots: {sorted((l.lot_number, str(l.quantity), str(l.expiry_date)) for l in lots)}")
    _check(len(lots) == 4, "b) load_candidate_lots returns OPENING + L1 + L2 + L3")

    # ── c) expiry on -> FEFO forced ──
    await _set_lot_settings(session, product_id, expiry=True, strategy=None)
    strategy, source = await _resolve(session, product_id)
    _check((strategy, source) == ("FEFO", "FORCED"), f"c) expiry on resolves to (FEFO, FORCED) (got {(strategy, source)})")

    lots = await load_candidate_lots(session, E2E_TENANT_ID, product_id, wh)
    fefo_plan = plan_allocation(lots, Decimal("20"), strategy, today)
    print(f"     FEFO plan for 20: {[(l.lot_number, str(l.quantity)) for l in fefo_plan.lines]}")
    _check([l.lot_id for l in fefo_plan.lines] == [opening_id, l2, l1],
           "c) FEFO order is OPENING, L2, L1")
    _check([l.quantity for l in fefo_plan.lines] == [Decimal("10"), Decimal("6"), Decimal("4")],
           "c) FEFO quantities are 10, 6, 4")
    _check(fefo_plan.shortfall == 0, "c) FEFO plan has no shortfall")
    _check([l.lot_id for l in fefo_plan.expired_skipped] == [l3], "c) L3 is in expired_skipped")
    _check(l3 not in [l.lot_id for l in fefo_plan.lines], "c) expired L3 is never allocated")

    # ── d) expiry off + LIFO ──
    await _set_lot_settings(session, product_id, expiry=False, strategy="LIFO")
    strategy, source = await _resolve(session, product_id)
    _check((strategy, source) == ("LIFO", "PRODUCT"), f"d) resolves to (LIFO, PRODUCT) (got {(strategy, source)})")

    lots = await load_candidate_lots(session, E2E_TENANT_ID, product_id, wh)
    lifo_plan = plan_allocation(lots, Decimal("20"), strategy, today)
    print(f"     LIFO plan for 20: {[(l.lot_number, str(l.quantity)) for l in lifo_plan.lines]}")
    _check(lifo_plan.lines[0].lot_id == l2, "d) LIFO takes L2 first")
    _check(lifo_plan.lines[-1].lot_id == opening_id, "d) LIFO takes OPENING last")
    _check([l.lot_id for l in lifo_plan.expired_skipped] == [l3], "d) L3 still skipped under LIFO")

    # ── e) allocate (locking), manual selection, override log ──
    await _set_lot_settings(session, product_id, expiry=True, strategy=None)
    strategy, _ = await _resolve(session, product_id)

    plan = await allocate(session, E2E_TENANT_ID, product_id, wh, Decimal("12"), strategy)
    print(f"     allocate(12) with row locks: {[(l.lot_number, str(l.quantity)) for l in plan.lines]}")
    _check([l.lot_id for l in plan.lines] == [opening_id, l2], "e) allocate(lock=True) succeeds: OPENING then L2")

    try:
        await allocate(session, E2E_TENANT_ID, product_id, wh, Decimal("1000"), strategy)
        _check(False, "e) allocate beyond stock raises InsufficientStockError")
    except InsufficientStockError as exc:
        _check(exc.available == Decimal("24"),
               f"e) allocate beyond stock raises InsufficientStockError (available={exc.available}, expired L3 excluded)")

    chosen = [
        {"lot_id": l1, "quantity": Decimal("8")},
        {"lot_id": opening_id, "quantity": Decimal("4")},
    ]
    plan, is_override = await validate_manual_selection(
        session, E2E_TENANT_ID, product_id, wh, Decimal("12"), chosen, strategy
    )
    _check(is_override is True, "e) validate_manual_selection choosing L1 first returns is_override True")

    _, same = await validate_manual_selection(
        session, E2E_TENANT_ID, product_id, wh, Decimal("12"),
        [{"lot_id": opening_id, "quantity": Decimal("10")}, {"lot_id": l2, "quantity": Decimal("2")}],
        strategy,
    )
    _check(same is False, "e) selection equal to the plan is not an override")

    for label, bad_chosen, bad_qty, expected in (
        ("expired lot", [{"lot_id": l3, "quantity": Decimal("5")}], Decimal("5"), "LOT_EXPIRED"),
        ("unknown lot", [{"lot_id": str(uuid.uuid4()), "quantity": Decimal("5")}], Decimal("5"), "LOT_NOT_IN_WAREHOUSE"),
        ("over balance", [{"lot_id": l2, "quantity": Decimal("7")}], Decimal("7"), "INSUFFICIENT_LOT_STOCK"),
        ("sum mismatch", [{"lot_id": l2, "quantity": Decimal("3")}], Decimal("5"), "SELECTION_QTY_MISMATCH"),
    ):
        try:
            await validate_manual_selection(
                session, E2E_TENANT_ID, product_id, wh, bad_qty, bad_chosen, strategy
            )
            _check(False, f"e) {label} raises {expected}")
        except DispatchError as exc:
            _check(exc.code == expected, f"e) {label} raises {expected} (got {exc.code})")

    override_args = (
        session, E2E_TENANT_ID, E2E_USER_ID, product_id, wh, "FEFO", "ISSUE", None,
        Decimal("12"), plan, chosen,
    )
    try:
        await record_override(*override_args, "   ")
        _check(False, "e) FEFO override with blank reason raises OVERRIDE_REASON_REQUIRED")
    except DispatchError as exc:
        _check(exc.code == "OVERRIDE_REASON_REQUIRED",
               f"e) FEFO override with blank reason raises OVERRIDE_REASON_REQUIRED (got {exc.code})")
    _check(await _override_count(session, product_id) == 0, "e) nothing inserted for the rejected override")

    override_id = await record_override(*override_args, "smoke: customer asked for the long-dated lot")
    count = await _override_count(session, product_id)
    _check(count == 1, f"e) FEFO override with a reason inserts one row (SELECT count = {count})")

    row = (await session.execute(
        text(
            "SELECT strategy::text AS strategy, movement_type, requested_qty, suggested, chosen, "
            "reason, overridden_by FROM lot_allocation_overrides WHERE id = :id"
        ),
        {"id": override_id},
    )).fetchone()
    print(f"     override row: strategy={row.strategy} movement_type={row.movement_type} "
          f"requested_qty={row.requested_qty} reason={row.reason!r}")
    print(f"     suggested={row.suggested}")
    print(f"     chosen={row.chosen}")
    _check([s["lot_number"] for s in row.suggested] == [opening.lot_number, "SMK-L2"],
           "e) stored suggested = engine order (OPENING, L2)")
    _check([c["lot_number"] for c in row.chosen] == ["SMK-L1", opening.lot_number],
           "e) stored chosen = user choice (L1, OPENING)")


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
            # ── f) never commit ──
            await session.rollback()
            print("ROLLED BACK")

    # ── post-rollback check from a NEW session ──
    async with AsyncSessionLocal() as verify_session:
        await set_rls_context(verify_session, E2E_TENANT_ID, E2E_USER_ID)
        product = (await verify_session.execute(
            text("SELECT id FROM products WHERE tenant_id = :tid AND sku = :sku"),
            {"tid": E2E_TENANT_ID, "sku": f"SMKD-{suffix}"},
        )).fetchone()
        overrides = (await verify_session.execute(
            text("SELECT count(*) AS cnt FROM lot_allocation_overrides WHERE tenant_id = :tid"),
            {"tid": E2E_TENANT_ID},
        )).fetchone()
        await verify_session.rollback()
    _check(product is None, "f) post-rollback: smoke product not found")
    _check(overrides.cnt == 0, f"f) post-rollback: tenant override rows = {overrides.cnt}")

    if _failures:
        print(f"SMOKE FAIL ({len(_failures)} failed)")
        return 1
    print("SMOKE PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
