"""Rollback-only real-DB smoke check for Issue and Adjustment lot posting
(InventoryService.issue_stock() + create_adjustment()/transition_adjustment()/
approve_adjustment() + the FEFO override path in services/dispatch_service.py).

Same approach as smoke_transfer_lots.py / smoke_transfer_receipt.py (their
helpers are imported): ONE async session against DATABASE_URL, RLS context
for the permanent zz-e2e-ta tenant, temporary nodes in organization_node,
service methods called directly, and NEVER a commit — everything is rolled
back in a `finally` block. audit_log() is replaced with a no-op (imported
already patched from smoke_transfer_receipt).

After every scenario, lot_totals_mismatch() is checked for the product: the
sum of lot_balances must equal inventory_balances at that warehouse.

Prints PASS/FAIL per assertion, then "ROLLED BACK". Exits 1 on any FAIL.

Usage:
    set -a; source .env; set +a
    python scripts/smoke_issue_adjust_lots.py
"""
from __future__ import annotations

import asyncio
import sys
import traceback
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

# Importing the template sets FEATURE_LOT_TRACKING, the backend sys.path, and
# (via smoke_transfer_receipt) patches inventory_service.audit_log to a no-op.
from smoke_transfer_lots import (  # noqa: E402
    E2E_TENANT_ID,
    E2E_USER_ID,
    _check,
    _failures,
    _lot_balances,
    _product_balance,
)
from smoke_transfer_receipt import (  # noqa: E402
    USER,
    _d,
    _make_product,
    _stock,
)

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import text  # noqa: E402

from shared.db.session import AsyncSessionLocal  # noqa: E402
from shared.db.rls import set_rls_context  # noqa: E402
from repositories.ledger_repo import record_transaction  # noqa: E402
from repositories.lot_repo import get_or_create_lot, lot_totals_mismatch  # noqa: E402
from schemas.inventory import (  # noqa: E402
    AdjustmentReasonCode,
    AdjustmentRequest,
    AdjustStockRequest,
    IssueStockRequest,
    LotPick,
)
from services.inventory_service import InventoryService  # noqa: E402


def _issue_ref(idempotency_key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"issue:{E2E_TENANT_ID}:{idempotency_key}"))


async def _issue_rows(session, product_id: str, issue_ref: str) -> list:
    return list((await session.execute(
        text(
            "SELECT lot_id, quantity, idempotency_key, reference_id FROM inventory_transactions "
            "WHERE tenant_id = :tid AND type = 'ISSUE' AND product_id = :pid "
            "AND reference_id = :ref ORDER BY lot_id"
        ),
        {"tid": E2E_TENANT_ID, "pid": product_id, "ref": issue_ref},
    )).fetchall())


async def _issue_count_plain(session, product_id: str) -> int:
    """ISSUE rows for a non-batch product (no reference_id scheme)."""
    return (await session.execute(
        text(
            "SELECT count(*) FROM inventory_transactions "
            "WHERE tenant_id = :tid AND type = 'ISSUE' AND product_id = :pid"
        ),
        {"tid": E2E_TENANT_ID, "pid": product_id},
    )).fetchone()[0]


async def _override_rows(session, reference_id: str) -> list:
    return list((await session.execute(
        text(
            "SELECT movement_type, reference_id FROM lot_allocation_overrides "
            "WHERE tenant_id = :tid AND reference_id = :ref"
        ),
        {"tid": E2E_TENANT_ID, "ref": reference_id},
    )).fetchall())


async def _adjustment_row(session, adjustment_id) -> Any:
    return (await session.execute(
        text(
            "SELECT status, product_id, warehouse_id, quantity_delta, reason_code, "
            "lot_id, lot_number, expiry_date, auto_lot "
            "FROM adjustment_orders WHERE id = :id AND tenant_id = :tid"
        ),
        {"id": str(adjustment_id), "tid": E2E_TENANT_ID},
    )).fetchone()


async def _adjustment_ledger_rows(session, adjustment_id) -> list:
    return list((await session.execute(
        text(
            "SELECT lot_id, quantity FROM inventory_transactions "
            "WHERE tenant_id = :tid AND type = 'ADJUSTMENT' AND reference_id = :ref"
        ),
        {"tid": E2E_TENANT_ID, "ref": str(adjustment_id)},
    )).fetchall())


async def _stock_lot_by_number(session, product_id: str, lot_number: str) -> Optional[Any]:
    return (await session.execute(
        text(
            "SELECT id, lot_number, expiry_date FROM stock_lots "
            "WHERE tenant_id = :tid AND product_id = :pid AND lot_number = :lot"
        ),
        {"tid": E2E_TENANT_ID, "pid": product_id, "lot": lot_number},
    )).fetchone()


async def _approve_adjustment(session, svc, adjustment_id) -> Any:
    """Mirror routers/adjust.py's /approve endpoint exactly."""
    row = (await session.execute(
        text(
            "SELECT status, product_id, warehouse_id, quantity_delta, reason_code "
            "FROM adjustment_orders WHERE id = :id"
        ),
        {"id": str(adjustment_id)},
    )).fetchone()
    if row.status == "DRAFT":
        await svc.transition_adjustment(USER, adjustment_id, "PENDING_APPROVAL")
    await svc.transition_adjustment(USER, adjustment_id, "APPROVED")
    body = AdjustStockRequest(
        product_id=row.product_id,
        warehouse_id=row.warehouse_id,
        quantity=Decimal(str(row.quantity_delta)),
        reason_code=row.reason_code,
        idempotency_key=f"adj:{adjustment_id}:post",
    )
    return await svc.approve_adjustment(USER, adjustment_id, body)


async def _http_code(coro) -> str:
    try:
        await coro
        return "no error"
    except HTTPException as exc:
        code = exc.detail.get("code") if isinstance(exc.detail, dict) else exc.detail
        return f"{exc.status_code} {code}"


# ─────────────────────────────── Issue scenarios ───────────────────────────────

async def _issue_i1_i2_i3(session, svc, wh, suffix) -> None:
    product_id = await _make_product(session, suffix, "ISSA", batch=True)
    lot_exp = await _stock(session, product_id, wh, "10", "LOT-EXP", -1)
    lot_near = await _stock(session, product_id, wh, "10", "LOT-NEAR", 30)
    lot_far = await _stock(session, product_id, wh, "10", "LOT-FAR", 90)

    key = f"smoke:issue:i1:{suffix}"
    ref = _issue_ref(key)
    body = IssueStockRequest(
        product_id=product_id, warehouse_id=wh, quantity=_d("15"),
        reason_code="SALE", idempotency_key=key,
    )

    # ── I1: engine allocation skips the expired lot ──
    resp = await svc.issue_stock(USER, body)
    rows = await _issue_rows(session, product_id, ref)
    got = {str(r.lot_id): abs(Decimal(str(r.quantity))) for r in rows}
    _check(got == {lot_near: _d("10"), lot_far: _d("5")},
           f"I1) ISSUE rows are NEAR -10, FAR -5 (got {[(str(r.lot_id), str(r.quantity)) for r in rows]})")
    _check(len({r.reference_id for r in rows}) == 1,
           "I1) both ISSUE rows share one reference_id")
    _check(
        all(r.idempotency_key == f"{key}:lot:{r.lot_id}" for r in rows),
        f"I1) keys are '<key>:lot:<lot_id>' (got {[r.idempotency_key for r in rows]})",
    )
    exp_balance = (await _lot_balances(session, product_id, wh)).get(lot_exp)
    _check(exp_balance == _d("10"), f"I1) EXPIRED lot untouched (got {exp_balance})")
    resp_lots = {str(l.lot_id): l.quantity for l in resp.lots}
    _check(resp_lots == got, f"I1) response lots match the ledger (got {resp_lots})")

    # ── I2: only 5 usable left (FAR) — INSUFFICIENT_STOCK with expired_qty=10 ──
    key2 = f"smoke:issue:i2:{suffix}"
    body2 = IssueStockRequest(
        product_id=product_id, warehouse_id=wh, quantity=_d("20"),
        reason_code="SALE", idempotency_key=key2,
    )
    before = await _issue_count_plain(session, product_id)
    got_code = "no error"
    try:
        await svc.issue_stock(USER, body2)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        got_code = f"{exc.status_code} {detail.get('code')} expired_qty={detail.get('expired_qty')}"
    after = await _issue_count_plain(session, product_id)
    _check(got_code == "422 INSUFFICIENT_STOCK expired_qty=10.0",
           f"I2) 422 INSUFFICIENT_STOCK, expired_qty 10 (got {got_code})")
    _check(after == before, f"I2) no new ISSUE rows ({before} -> {after})")

    # ── I3: replay I1 ──
    rows_before = await _issue_rows(session, product_id, ref)
    balances_before = await _lot_balances(session, product_id, wh)
    replay = await svc.issue_stock(USER, body)
    rows_after = await _issue_rows(session, product_id, ref)
    _check(len(rows_after) == len(rows_before) == 2,
           f"I3) replay: ISSUE row count unchanged ({len(rows_before)} -> {len(rows_after)})")
    _check(await _lot_balances(session, product_id, wh) == balances_before,
           "I3) replay: lot balances unchanged")
    replay_lots = {str(l.lot_id): l.quantity for l in replay.lots}
    _check(replay_lots == got, f"I3) replay returns the same rows (got {replay_lots})")

    mismatch = await lot_totals_mismatch(session, E2E_TENANT_ID, product_id, wh)
    _check(mismatch is None, f"I1-3) lot_totals_mismatch returns nothing (got {mismatch})")


async def _issue_i4_override(session, svc, wh, suffix) -> None:
    product_id = await _make_product(session, suffix, "ISSB", batch=True)
    lot_exp = await _stock(session, product_id, wh, "10", "LOT-EXP4", -1)
    lot_near = await _stock(session, product_id, wh, "10", "LOT-NEAR4", 30)
    lot_far = await _stock(session, product_id, wh, "10", "LOT-FAR4", 90)

    selection = [LotPick(lot_id=lot_far, quantity=_d("8"))]

    # ── no reason, permitted: OVERRIDE_REASON_REQUIRED ──
    key_a = f"smoke:issue:i4a:{suffix}"
    body_a = IssueStockRequest(
        product_id=product_id, warehouse_id=wh, quantity=_d("8"),
        reason_code="SALE", idempotency_key=key_a, lot_selections=selection,
    )
    count_before = await _issue_count_plain(session, product_id)
    got = await _http_code(
        svc.issue_stock(USER, body_a, can_fefo_override=True, can_lot_select=False)
    )
    _check(got == "422 OVERRIDE_REASON_REQUIRED", f"I4) no reason: 422 OVERRIDE_REASON_REQUIRED (got {got})")
    _check(await _issue_count_plain(session, product_id) == count_before,
           "I4) no reason: no new ledger rows")

    # ── reason given, not permitted: OVERRIDE_NOT_PERMITTED ──
    key_b = f"smoke:issue:i4b:{suffix}"
    body_b = IssueStockRequest(
        product_id=product_id, warehouse_id=wh, quantity=_d("8"),
        reason_code="SALE", idempotency_key=key_b, lot_selections=selection,
        override_reason="manual pick",
    )
    got = await _http_code(
        svc.issue_stock(USER, body_b, can_fefo_override=False, can_lot_select=False)
    )
    _check(got == "403 OVERRIDE_NOT_PERMITTED", f"I4) not permitted: 403 OVERRIDE_NOT_PERMITTED (got {got})")
    _check(await _issue_count_plain(session, product_id) == count_before,
           "I4) not permitted: no new ledger rows")

    # ── permitted + reason: posted, FAR only (not engine order — NEAR has stock too) ──
    key_c = f"smoke:issue:i4c:{suffix}"
    ref_c = _issue_ref(key_c)
    body_c = IssueStockRequest(
        product_id=product_id, warehouse_id=wh, quantity=_d("8"),
        reason_code="SALE", idempotency_key=key_c, lot_selections=selection,
        override_reason="manual pick for FAR batch",
    )
    resp = await svc.issue_stock(USER, body_c, can_fefo_override=True, can_lot_select=False)
    rows = await _issue_rows(session, product_id, ref_c)
    got_rows = {str(r.lot_id): abs(Decimal(str(r.quantity))) for r in rows}
    _check(got_rows == {lot_far: _d("8")}, f"I4) posted: one ISSUE row, FAR -8 (got {got_rows})")
    _check(resp.is_override, "I4) response flags is_override=True")
    overrides = await _override_rows(session, ref_c)
    _check(
        len(overrides) == 1 and overrides[0].movement_type == "ISSUE",
        f"I4) one lot_allocation_overrides row, movement_type ISSUE (got {len(overrides)})",
    )
    near_balance = (await _lot_balances(session, product_id, wh)).get(lot_near)
    _check(near_balance == _d("10"), f"I4) NEAR untouched by the override (got {near_balance})")

    mismatch = await lot_totals_mismatch(session, E2E_TENANT_ID, product_id, wh)
    _check(mismatch is None, f"I4) lot_totals_mismatch returns nothing (got {mismatch})")


async def _issue_i5_non_batch(session, svc, wh, suffix) -> None:
    product_id = await _make_product(session, suffix, "ISSC", batch=False)
    await record_transaction(
        session, E2E_TENANT_ID, "RECEIVE", product_id, wh, _d("10"), E2E_USER_ID,
        f"smoke:issue:i5:receive:{uuid.uuid4()}", source="WEB",
    )
    key = f"smoke:issue:i5:{suffix}"
    body = IssueStockRequest(
        product_id=product_id, warehouse_id=wh, quantity=_d("3"),
        reason_code="SALE", idempotency_key=key,
    )
    resp = await svc.issue_stock(USER, body)
    rows = list((await session.execute(
        text(
            "SELECT lot_id, quantity, idempotency_key FROM inventory_transactions "
            "WHERE tenant_id = :tid AND type = 'ISSUE' AND product_id = :pid"
        ),
        {"tid": E2E_TENANT_ID, "pid": product_id},
    )).fetchall())
    _check(
        len(rows) == 1 and rows[0].lot_id is None and rows[0].idempotency_key == key,
        f"I5) non-batch: one ISSUE row, lot_id NULL, key unchanged (got {[(r.lot_id, r.idempotency_key) for r in rows]})",
    )
    _check(abs(Decimal(str(rows[0].quantity))) == _d("3"), "I5) ISSUE quantity is 3")
    _check(resp.quantity == _d("3"), "I5) response quantity is 3")


# ────────────────────────────── Adjustment scenarios ──────────────────────────

async def _adj_a1_expiry(session, svc, wh, suffix) -> None:
    product_id = await _make_product(session, suffix, "ADJ1", batch=True)
    lot_exp = await _stock(session, product_id, wh, "10", "LOT-A1", -1)

    body = AdjustmentRequest(
        warehouse_id=wh, product_id=product_id, quantity_delta=_d("4"),
        reason_code=AdjustmentReasonCode.EXPIRY, lot_id=lot_exp,
        idempotency_key=f"smoke:adj:a1:{suffix}",
    )
    created = await svc.create_adjustment(USER, body)
    _check(created.status == "DRAFT", "A1) create: DRAFT")
    posted = await _approve_adjustment(session, svc, created.adjustment_id)
    _check(posted.status == "POSTED", f"A1) posted via approve-route (status {posted.status})")
    _check(posted.quantity_delta == _d("-4"),
           f"A1) EXPIRY forces negative: posted -4 (got {posted.quantity_delta})")
    ledger = await _adjustment_ledger_rows(session, created.adjustment_id)
    _check(
        len(ledger) == 1 and str(ledger[0].lot_id) == lot_exp
        and Decimal(str(ledger[0].quantity)) == _d("-4"),
        f"A1) ledger row carries lot_id and -4 (got {[(str(r.lot_id), str(r.quantity)) for r in ledger]})",
    )
    balance = (await _lot_balances(session, product_id, wh)).get(lot_exp)
    _check(balance == _d("6"), f"A1) EXPIRED lot balance now 6 (got {balance})")

    mismatch = await lot_totals_mismatch(session, E2E_TENANT_ID, product_id, wh)
    _check(mismatch is None, f"A1) lot_totals_mismatch returns nothing (got {mismatch})")


async def _adj_a2_new_lot_by_number(session, svc, wh, suffix) -> None:
    product_id = await _make_product(session, suffix, "ADJ2", batch=True)
    lot_number = f"SMK-A2-{suffix}"
    expiry = date.today() + timedelta(days=45)

    body = AdjustmentRequest(
        warehouse_id=wh, product_id=product_id, quantity_delta=_d("6"),
        reason_code=AdjustmentReasonCode.RETURN, lot_number=lot_number,
        expiry_date=expiry, idempotency_key=f"smoke:adj:a2:{suffix}",
    )
    created = await svc.create_adjustment(USER, body)
    before_lot = await _stock_lot_by_number(session, product_id, lot_number)
    _check(before_lot is None, "A2) create: no stock_lots row yet")

    posted = await _approve_adjustment(session, svc, created.adjustment_id)
    _check(posted.status == "POSTED", "A2) posted via approve-route")
    after_lot = await _stock_lot_by_number(session, product_id, lot_number)
    _check(after_lot is not None, "A2) posting created the stock_lots row")
    row = await _adjustment_row(session, created.adjustment_id)
    _check(
        after_lot is not None and str(row.lot_id) == str(after_lot.id),
        f"A2) adjustment_orders.lot_id points to the new lot (got {row.lot_id} vs {after_lot.id if after_lot else None})",
    )
    balance = (await _lot_balances(session, product_id, wh)).get(str(after_lot.id)) if after_lot else None
    _check(balance == _d("6"), f"A2) lot holds the posted quantity 6 (got {balance})")

    mismatch = await lot_totals_mismatch(session, E2E_TENANT_ID, product_id, wh)
    _check(mismatch is None, f"A2) lot_totals_mismatch returns nothing (got {mismatch})")


async def _adj_a3_auto_lot(session, svc, wh, suffix) -> None:
    product_id = await _make_product(session, suffix, "ADJ3", batch=True)
    expiry = date.today() + timedelta(days=55)

    body = AdjustmentRequest(
        warehouse_id=wh, product_id=product_id, quantity_delta=_d("7"),
        reason_code=AdjustmentReasonCode.RETURN, auto_lot=True,
        expiry_date=expiry, idempotency_key=f"smoke:adj:a3:{suffix}",
    )
    created = await svc.create_adjustment(USER, body)
    count_before = (await session.execute(
        text("SELECT count(*) FROM stock_lots WHERE tenant_id = :tid AND product_id = :pid"),
        {"tid": E2E_TENANT_ID, "pid": product_id},
    )).fetchone()[0]
    _check(count_before == 0, "A3) create: auto lot not created yet")

    posted = await _approve_adjustment(session, svc, created.adjustment_id)
    _check(posted.status == "POSTED", "A3) posted via approve-route")
    row = await _adjustment_row(session, created.adjustment_id)
    _check(row.lot_id is not None, "A3) adjustment_orders.lot_id set at posting")
    count_after = (await session.execute(
        text("SELECT count(*) FROM stock_lots WHERE tenant_id = :tid AND product_id = :pid"),
        {"tid": E2E_TENANT_ID, "pid": product_id},
    )).fetchone()[0]
    _check(count_after == 1, f"A3) exactly one lot created at posting (got {count_after})")

    mismatch = await lot_totals_mismatch(session, E2E_TENANT_ID, product_id, wh)
    _check(mismatch is None, f"A3) lot_totals_mismatch returns nothing (got {mismatch})")


async def _adj_a4_existing_lot_new_warehouse(session, svc, wh, other_wh, suffix) -> None:
    product_id = await _make_product(session, suffix, "ADJ4", batch=True)
    lot_id = await get_or_create_lot(
        session, E2E_TENANT_ID, product_id, f"LOT-A4-{suffix}",
        date.today() + timedelta(days=60), E2E_USER_ID,
    )
    await record_transaction(
        session, E2E_TENANT_ID, "RECEIVE", product_id, other_wh, _d("10"), E2E_USER_ID,
        f"smoke:adj:a4:receive:{uuid.uuid4()}", lot_id=lot_id, lot_number=f"LOT-A4-{suffix}",
        expiry_date=date.today() + timedelta(days=60), source="WEB",
    )
    before = (await _lot_balances(session, product_id, wh)).get(lot_id)
    _check(before is None, "A4) setup: the lot has no lot_balances row at wh yet")

    body = AdjustmentRequest(
        warehouse_id=wh, product_id=product_id, quantity_delta=_d("5"),
        reason_code=AdjustmentReasonCode.RETURN, lot_id=lot_id,
        idempotency_key=f"smoke:adj:a4:{suffix}",
    )
    created = await svc.create_adjustment(USER, body)
    posted = await _approve_adjustment(session, svc, created.adjustment_id)
    _check(posted.status == "POSTED", "A4) posted via approve-route")
    after = (await _lot_balances(session, product_id, wh)).get(lot_id)
    _check(after == _d("5"), f"A4) lot_balances row created at wh with quantity 5 (got {after})")

    mismatch = await lot_totals_mismatch(session, E2E_TENANT_ID, product_id, wh)
    _check(mismatch is None, f"A4) lot_totals_mismatch at wh returns nothing (got {mismatch})")


async def _adj_a5_insufficient(session, svc, wh, suffix) -> None:
    # ── A5a: negative larger than the lot balance -> 422 at create ──
    product_a = await _make_product(session, suffix, "ADJ5A", batch=True)
    lot_small = await _stock(session, product_a, wh, "5", "LOT-A5A", 30)
    body_a = AdjustmentRequest(
        warehouse_id=wh, product_id=product_a, quantity_delta=_d("-10"),
        reason_code=AdjustmentReasonCode.COUNT_DISCREPANCY, lot_id=lot_small,
        idempotency_key=f"smoke:adj:a5a:{suffix}",
    )
    savepoint = await session.begin_nested()
    got = await _http_code(svc.create_adjustment(USER, body_a))
    await savepoint.rollback()
    _check(got == "422 INSUFFICIENT_LOT_STOCK", f"A5a) create: 422 INSUFFICIENT_LOT_STOCK (got {got})")

    # ── A5b: valid negative at create, lot drained before posting -> fails at posting ──
    # A second lot (farther expiry, so FEFO leaves it alone) keeps the PRODUCT-level
    # balance positive after the drain, so the failure below is the LOT-level floor
    # check (INSUFFICIENT_LOT_STOCK), not the product-level one (INSUFFICIENT_STOCK).
    product_b = await _make_product(session, suffix, "ADJ5B", batch=True)
    lot_drain = await _stock(session, product_b, wh, "10", "LOT-A5B", 30)
    await _stock(session, product_b, wh, "20", "LOT-A5B-OTHER", 200)
    body_b = AdjustmentRequest(
        warehouse_id=wh, product_id=product_b, quantity_delta=_d("-4"),
        reason_code=AdjustmentReasonCode.COUNT_DISCREPANCY, lot_id=lot_drain,
        idempotency_key=f"smoke:adj:a5b:{suffix}",
    )
    created_b = await svc.create_adjustment(USER, body_b)
    _check(created_b.status == "DRAFT", "A5b) create: valid negative accepted (DRAFT)")

    await svc.transition_adjustment(USER, created_b.adjustment_id, "PENDING_APPROVAL")

    # Drain LOT-A5B completely via a plain engine Issue (it's the only lot with stock).
    drain_key = f"smoke:adj:a5b:drain:{suffix}"
    await svc.issue_stock(USER, IssueStockRequest(
        product_id=product_b, warehouse_id=wh, quantity=_d("10"),
        reason_code="SALE", idempotency_key=drain_key,
    ))
    drained_balance = (await _lot_balances(session, product_b, wh)).get(lot_drain)
    _check(drained_balance == _d("0"), f"A5b) setup: lot drained to 0 (got {drained_balance})")

    await svc.transition_adjustment(USER, created_b.adjustment_id, "APPROVED")

    savepoint = await session.begin_nested()
    row = await _adjustment_row(session, created_b.adjustment_id)
    adj_body = AdjustStockRequest(
        product_id=row.product_id, warehouse_id=row.warehouse_id,
        quantity=Decimal(str(row.quantity_delta)), reason_code=row.reason_code,
        idempotency_key=f"adj:{created_b.adjustment_id}:post",
    )
    got = await _http_code(svc.approve_adjustment(USER, created_b.adjustment_id, adj_body))
    await savepoint.rollback()
    _check(got == "422 INSUFFICIENT_LOT_STOCK", f"A5b) posting: 422 INSUFFICIENT_LOT_STOCK (got {got})")

    ledger = await _adjustment_ledger_rows(session, created_b.adjustment_id)
    _check(len(ledger) == 0, f"A5b) no ADJUSTMENT ledger row (got {len(ledger)})")
    status_after = (await _adjustment_row(session, created_b.adjustment_id)).status
    _check(status_after == "APPROVED",
           f"A5b) adjustment not POSTED (status {status_after})")


async def _adj_a6_lot_required(session, svc, wh, suffix) -> None:
    product_id = await _make_product(session, suffix, "ADJ6", batch=True)
    body = AdjustmentRequest(
        warehouse_id=wh, product_id=product_id, quantity_delta=_d("-5"),
        reason_code=AdjustmentReasonCode.OTHER,
        idempotency_key=f"smoke:adj:a6:{suffix}",
    )
    savepoint = await session.begin_nested()
    got = await _http_code(svc.create_adjustment(USER, body))
    await savepoint.rollback()
    _check(got == "422 LOT_REQUIRED", f"A6) negative without lot_id: 422 LOT_REQUIRED (got {got})")


async def _adj_a7_non_batch(session, svc, wh, suffix) -> None:
    product_id = await _make_product(session, suffix, "ADJ7", batch=False)

    bad = AdjustmentRequest(
        warehouse_id=wh, product_id=product_id, quantity_delta=_d("3"),
        reason_code=AdjustmentReasonCode.RETURN, lot_number="SHOULD-FAIL",
        idempotency_key=f"smoke:adj:a7:bad:{suffix}",
    )
    savepoint = await session.begin_nested()
    got = await _http_code(svc.create_adjustment(USER, bad))
    await savepoint.rollback()
    _check(got == "422 LOT_NOT_TRACKED", f"A7) lot_number on non-batch: 422 LOT_NOT_TRACKED (got {got})")

    good = AdjustmentRequest(
        warehouse_id=wh, product_id=product_id, quantity_delta=_d("3"),
        reason_code=AdjustmentReasonCode.RETURN,
        idempotency_key=f"smoke:adj:a7:good:{suffix}",
    )
    created = await svc.create_adjustment(USER, good)
    posted = await _approve_adjustment(session, svc, created.adjustment_id)
    _check(posted.status == "POSTED" and posted.lot_id is None,
           f"A7) without lot fields: posts as before (status {posted.status}, lot_id {posted.lot_id})")


async def _run(session, suffix: str) -> None:
    await set_rls_context(session, E2E_TENANT_ID, E2E_USER_ID)

    wh = str(uuid.uuid4())
    other_wh = str(uuid.uuid4())
    for node_id, label, code in (
        (wh, "Smoke Issue-Adjust Primary", f"SMOKE-IA-{suffix}"),
        (other_wh, "Smoke Issue-Adjust Secondary", f"SMOKE-IA2-{suffix}"),
    ):
        await session.execute(
            text(
                "INSERT INTO organization_node "
                "(id, tenant_id, name, code, hierarchy_level, is_stock_holding, is_active) "
                "VALUES (:id, :tid, :name, :code, 1, true, true)"
            ),
            {"id": node_id, "tid": E2E_TENANT_ID, "name": f"{label} {suffix}", "code": code},
        )
    print(f"     wh={wh}  other_wh={other_wh}")

    svc = InventoryService(session)

    print("--- Issue ---")
    await _issue_i1_i2_i3(session, svc, wh, suffix)
    await _issue_i4_override(session, svc, wh, suffix)
    await _issue_i5_non_batch(session, svc, wh, suffix)

    print("--- Adjustment ---")
    print("     NOTE: zz-e2e-ta has no adjustment_approval_rules rows, so "
          "check_adjustment_self_approval() always returns (False, None, None) "
          "— self-approval at submit is structurally impossible for this tenant. "
          "Every A-scenario below posts via the approve-route "
          "(submit -> APPROVED -> approve_adjustment), never the self-approve path.")
    await _adj_a1_expiry(session, svc, wh, suffix)
    await _adj_a2_new_lot_by_number(session, svc, wh, suffix)
    await _adj_a3_auto_lot(session, svc, wh, suffix)
    await _adj_a4_existing_lot_new_warehouse(session, svc, wh, other_wh, suffix)
    await _adj_a5_insufficient(session, svc, wh, suffix)
    await _adj_a6_lot_required(session, svc, wh, suffix)
    await _adj_a7_non_batch(session, svc, wh, suffix)


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
        products = (await verify_session.execute(
            text("SELECT count(*) FROM products WHERE tenant_id = :tid AND sku LIKE :sku"),
            {"tid": E2E_TENANT_ID, "sku": f"SMKR-%-{suffix}"},
        )).scalar()
        adjustments = (await verify_session.execute(
            text(
                "SELECT count(*) FROM adjustment_orders a "
                "JOIN products p ON p.id = a.product_id "
                "WHERE a.tenant_id = :tid AND p.sku LIKE :sku"
            ),
            {"tid": E2E_TENANT_ID, "sku": f"SMKR-%-{suffix}"},
        )).scalar()
        await verify_session.rollback()
    _check(products == 0, f"post-rollback: smoke products = {products}")
    _check(adjustments == 0, f"post-rollback: smoke adjustment rows = {adjustments}")

    if _failures:
        print(f"SMOKE FAIL ({len(_failures)} failed)")
        return 1
    print("SMOKE PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
