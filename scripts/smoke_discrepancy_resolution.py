"""Rollback-only real-DB smoke check for FEFO phase D2: resolving and listing
transfer discrepancies (services/transfer_discrepancies.py, migration 088).

Same approach as smoke_transfer_receipt.py (its helpers are imported): ONE async
session against DATABASE_URL, RLS context for the permanent zz-e2e-ta tenant,
and NEVER a commit — everything is rolled back in a `finally` block.

Fixtures are organization_node rows only (no rows in the old warehouses table):

    PARENT  (approval-only, is_stock_holding=false)
      +- SRC  (stock-holding)
      +- DST  (stock-holding)
    OTHER   (stock-holding, a root outside PARENT)

Every scenario starts from a fresh short receipt driven through the real service
functions (approve, dispatch, receive with a receipt body); discrepancy rows are
never hand-inserted. Resolution and listing call resolve_discrepancy() and
list_discrepancies() directly. resolve_discrepancy() writes its audit_logs row in
the caller's transaction, so the rollback removes it; audit_log() (which opens its
own session and commits) is a no-op for this run, as in smoke_transfer_receipt.py.

Prints one PASS/FAIL line per scenario, then a summary. Exits 1 on any FAIL.

Usage:
    set -a; source .env; set +a
    python scripts/smoke_discrepancy_resolution.py
"""
from __future__ import annotations

import asyncio
import sys
import traceback
import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Optional

# Importing the receipt smoke sets FEATURE_LOT_TRACKING, the backend sys.path and
# the audit_log() no-op.
from smoke_transfer_receipt import (  # noqa: E402
    E2E_TENANT_ID,
    E2E_USER_ID,
    USER,
    _body,
    _d,
    _in_transit_transfer,
    _lot_balances,
    _make_product,
    _product_balance,
    _stock,
)

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import text  # noqa: E402

from shared.db.session import AsyncSessionLocal  # noqa: E402
from shared.db.rls import set_rls_context  # noqa: E402
from repositories.ledger_repo import record_transaction  # noqa: E402
from schemas.inventory import ResolveDiscrepancyRequest  # noqa: E402
from services.inventory_service import InventoryService  # noqa: E402
from services.transfer_discrepancies import list_discrepancies, resolve_discrepancy  # noqa: E402

N = _d("4")          # missing quantity of every short receipt: sent 10, received 6
SENT, RECEIVED = "10", "6"
AUDIT_ACTION = "transfer:resolve_discrepancy"

_results: list[bool] = []


def _report(name: str, label: str, problems: list[str]) -> None:
    ok = not problems
    _results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'} {name}  {label}" + ("" if ok else f"  <- {'; '.join(problems)}"))


def _user(role: str, node: Optional[str]) -> SimpleNamespace:
    return SimpleNamespace(
        tenant_id=E2E_TENANT_ID, user_id=E2E_USER_ID, role=role,
        warehouse_id=node, level_number=None,
    )


class Ctx:
    """Fixtures and the discrepancy ids created so far."""

    def __init__(self, svc: InventoryService, parent: str, src: str, dst: str, other: str) -> None:
        self.svc, self.parent, self.src, self.dst, self.other = svc, parent, src, dst, other
        self.batch_product = ""
        self.plain_product = ""
        self.lot_a = ""
        self.lot_b = ""
        self.s1: tuple[str, str] = ("", "")     # (transfer_id, discrepancy_id) of S1
        self.smoke_ids: list[str] = []          # every discrepancy created in this run
        self.resolved_ids: list[str] = []       # every successful resolve


async def _short_receipt(session, ctx: Ctx, reason: str, batch: bool = True) -> tuple[str, str]:
    """A fresh transfer SRC -> DST received short (N missing). Returns (transfer_id, discrepancy_id)."""
    if batch:
        product_id = ctx.batch_product
        await _stock(session, product_id, ctx.src, SENT, "LOT-A", 30)   # keep lot A the FEFO pick
        lot_id: Optional[str] = ctx.lot_a
    else:
        product_id = ctx.plain_product
        await _stock(session, product_id, ctx.src, SENT)
        lot_id = None
    transfer_id, line = await _in_transit_transfer(session, ctx.svc, ctx.src, ctx.dst, product_id, SENT)
    await ctx.svc.receive_transfer(
        USER, uuid.UUID(transfer_id), _body((line.id, lot_id, RECEIVED, reason, f"smoke {reason}")),
    )
    rows = (await session.execute(
        text("SELECT id::text AS id FROM transfer_discrepancies "
             "WHERE tenant_id = :tid AND transfer_order_id = :xfer"),
        {"tid": E2E_TENANT_ID, "xfer": transfer_id},
    )).fetchall()
    assert len(rows) == 1, f"short receipt produced {len(rows)} discrepancy rows"
    ctx.smoke_ids.append(rows[0].id)
    return transfer_id, rows[0].id


async def _resolve(session, ctx: Ctx, user, transfer_id, disc_id, resolution,
                   lot_id: Optional[str] = None, note: Optional[str] = None):
    body = ResolveDiscrepancyRequest(
        resolution=resolution, lot_id=uuid.UUID(lot_id) if lot_id else None, note=note,
    )
    out = await resolve_discrepancy(session, user, transfer_id, disc_id, body)
    ctx.resolved_ids.append(disc_id)
    return out


async def _snap(session, product_id: str, wh: str) -> tuple[Decimal, dict[str, Decimal]]:
    return await _product_balance(session, product_id, wh), await _lot_balances(session, product_id, wh)


def _delta(after: dict[str, Decimal], before: dict[str, Decimal], lot: str) -> Decimal:
    return after.get(lot, Decimal("0")) - before.get(lot, Decimal("0"))


async def _resolution_rows(session, transfer_id: str, disc_id: str) -> list[tuple]:
    """(type, warehouse_id, lot_id, quantity) of the ledger rows this resolution wrote."""
    rows = (await session.execute(
        text(
            "SELECT type::text AS type, warehouse_id::text AS wh, lot_id::text AS lot, quantity "
            "FROM inventory_transactions "
            "WHERE tenant_id = :tid AND reference_id::text = :xfer AND idempotency_key LIKE :pfx "
            "ORDER BY type::text, quantity"
        ),
        {"tid": E2E_TENANT_ID, "xfer": transfer_id,
         "pfx": f"transfer:{transfer_id}:discrepancy:{disc_id}:%"},
    )).fetchall()
    return [(r.type, r.wh, r.lot, Decimal(str(r.quantity))) for r in rows]


async def _ledger_count(session, product_id: str) -> int:
    return (await session.execute(
        text("SELECT count(*) FROM inventory_transactions WHERE tenant_id = :tid AND product_id = :pid"),
        {"tid": E2E_TENANT_ID, "pid": product_id},
    )).scalar()


async def _disc_state(session, disc_id: str) -> Any:
    return (await session.execute(
        text("SELECT status, resolution, resolution_note, resolved_lot_id::text AS resolved_lot_id "
             "FROM transfer_discrepancies WHERE id = :id AND tenant_id = :tid"),
        {"id": disc_id, "tid": E2E_TENANT_ID},
    )).fetchone()


async def _expect_error(
    session, product_id: str, call: Callable[[], Awaitable[Any]],
) -> tuple[Optional[int], Optional[str], int, int, int]:
    """Run `call` inside a savepoint that is always rolled back.

    Returns (status, code, ledger rows before, ledger rows inside the savepoint
    after the failure, ledger rows after the savepoint rollback)."""
    before = await _ledger_count(session, product_id)
    savepoint = await session.begin_nested()
    status: Optional[int] = None
    code: Optional[str] = None
    try:
        await call()
    except HTTPException as exc:
        status = exc.status_code
        code = exc.detail.get("code") if isinstance(exc.detail, dict) else str(exc.detail)
    except Exception as exc:  # noqa: BLE001 — a DB error here is a finding, reported below
        code = f"{type(exc).__name__}: {str(exc)[:120]}"
    inside = await _ledger_count(session, product_id)
    await savepoint.rollback()
    return status, code, before, inside, await _ledger_count(session, product_id)


# ── scenarios ────────────────────────────────────────────────────────────────

async def _s1(session, ctx: Ctx) -> None:
    transfer_id, disc_id = await _short_receipt(session, ctx, "SHORT")
    ctx.s1 = (transfer_id, disc_id)
    src_b, dst_b = await _snap(session, ctx.batch_product, ctx.src), await _snap(session, ctx.batch_product, ctx.dst)
    out = await _resolve(session, ctx, USER, transfer_id, disc_id, "RETURNED")
    src_a, dst_a = await _snap(session, ctx.batch_product, ctx.src), await _snap(session, ctx.batch_product, ctx.dst)
    rows = await _resolution_rows(session, transfer_id, disc_id)
    problems = []
    if _delta(src_a[1], src_b[1], ctx.lot_a) != N:
        problems.append(f"SRC lot A delta {_delta(src_a[1], src_b[1], ctx.lot_a)}")
    if src_a[0] - src_b[0] != N:
        problems.append(f"SRC product delta {src_a[0] - src_b[0]}")
    if dst_a != dst_b:
        problems.append(f"DST changed {dst_b} -> {dst_a}")
    if rows != [("TRANSFER_REVERSAL", ctx.src, ctx.lot_a, N)]:
        problems.append(f"rows {rows}")
    if out.status != "RESOLVED" or out.resolution != "RETURNED":
        problems.append(f"out {out.status}/{out.resolution}")
    _report("S1", "SHORT -> RETURNED: SRC lot A and product +4, DST unchanged, one TRANSFER_REVERSAL", problems)


async def _s2(session, ctx: Ctx) -> None:
    transfer_id, disc_id = await _short_receipt(session, ctx, "SHORT")
    src_b, dst_b = await _snap(session, ctx.batch_product, ctx.src), await _snap(session, ctx.batch_product, ctx.dst)
    await _resolve(session, ctx, USER, transfer_id, disc_id, "ARRIVED_LATE")
    src_a, dst_a = await _snap(session, ctx.batch_product, ctx.src), await _snap(session, ctx.batch_product, ctx.dst)
    rows = await _resolution_rows(session, transfer_id, disc_id)
    problems = []
    if _delta(dst_a[1], dst_b[1], ctx.lot_a) != N:
        problems.append(f"DST lot A delta {_delta(dst_a[1], dst_b[1], ctx.lot_a)}")
    if dst_a[0] - dst_b[0] != N:
        problems.append(f"DST product delta {dst_a[0] - dst_b[0]}")
    if src_a != src_b:
        problems.append(f"SRC changed {src_b} -> {src_a}")
    if rows != [("TRANSFER_IN", ctx.dst, ctx.lot_a, N)]:
        problems.append(f"rows {rows}")
    _report("S2", "SHORT -> ARRIVED_LATE: DST lot A and product +4, one TRANSFER_IN", problems)


async def _s3(session, ctx: Ctx) -> None:
    transfer_id, disc_id = await _short_receipt(session, ctx, "DAMAGED")
    count_before = await _ledger_count(session, ctx.batch_product)
    out = await _resolve(session, ctx, USER, transfer_id, disc_id, "WRITTEN_OFF", note="smoke: destroyed on site")
    count_after = await _ledger_count(session, ctx.batch_product)
    state = await _disc_state(session, disc_id)
    problems = []
    if count_after != count_before:
        problems.append(f"ledger rows {count_before} -> {count_after}")
    if state.status != "RESOLVED" or state.resolution != "WRITTEN_OFF":
        problems.append(f"state {state.status}/{state.resolution}")
    if state.resolution_note != "smoke: destroyed on site" or out.resolution_note != state.resolution_note:
        problems.append(f"note {state.resolution_note!r}")
    _report("S3", "DAMAGED -> WRITTEN_OFF: no ledger rows, RESOLVED, note stored", problems)


async def _s4(session, ctx: Ctx) -> None:
    await _stock(session, ctx.batch_product, ctx.src, "10", "LOT-B", 60)
    transfer_id, disc_id = await _short_receipt(session, ctx, "WRONG_LOT")
    src_b, dst_b = await _snap(session, ctx.batch_product, ctx.src), await _snap(session, ctx.batch_product, ctx.dst)
    out = await _resolve(session, ctx, USER, transfer_id, disc_id, "RECEIVED_AS_LOT", lot_id=ctx.lot_b)
    src_a, dst_a = await _snap(session, ctx.batch_product, ctx.src), await _snap(session, ctx.batch_product, ctx.dst)
    rows = await _resolution_rows(session, transfer_id, disc_id)
    problems = []
    for label, got, want in (
        ("SRC lot A", _delta(src_a[1], src_b[1], ctx.lot_a), N),
        ("SRC lot B", _delta(src_a[1], src_b[1], ctx.lot_b), -N),
        ("SRC product", src_a[0] - src_b[0], Decimal("0")),
        ("DST lot B", _delta(dst_a[1], dst_b[1], ctx.lot_b), N),
        ("DST lot A", _delta(dst_a[1], dst_b[1], ctx.lot_a), Decimal("0")),
        ("DST product", dst_a[0] - dst_b[0], N),
    ):
        if got != want:
            problems.append(f"{label} delta {got} (want {want})")
    want_rows = sorted([
        ("TRANSFER_REVERSAL", ctx.src, ctx.lot_a, N),
        ("TRANSFER_OUT", ctx.src, ctx.lot_b, -N),
        ("TRANSFER_IN", ctx.dst, ctx.lot_b, N),
    ])
    if sorted(rows) != want_rows:
        problems.append(f"rows {rows}")
    if str(out.resolved_lot_id) != ctx.lot_b:
        problems.append(f"resolved_lot_id {out.resolved_lot_id}")
    _report("S4", "WRONG_LOT -> RECEIVED_AS_LOT (B): A +4, B -4, SRC net 0, DST B +4; REVERSAL+OUT+IN", problems)


async def _s5(session, ctx: Ctx) -> None:
    transfer_id, disc_id = await _short_receipt(session, ctx, "SHORT", batch=False)
    src_before = await _product_balance(session, ctx.plain_product, ctx.src)
    await _resolve(session, ctx, USER, transfer_id, disc_id, "RETURNED")
    src_after = await _product_balance(session, ctx.plain_product, ctx.src)
    rows = await _resolution_rows(session, transfer_id, disc_id)
    problems = []
    if src_after - src_before != N:
        problems.append(f"SRC product delta {src_after - src_before}")
    if rows != [("TRANSFER_REVERSAL", ctx.src, None, N)]:
        problems.append(f"rows {rows}")
    _report("S5", "non-batch SHORT -> RETURNED: SRC product +4, ledger lot_id NULL", problems)


async def _s6(session, ctx: Ctx) -> None:
    transfer_id, disc_id = ctx.s1
    status, code, before, inside, after = await _expect_error(
        session, ctx.batch_product,
        lambda: resolve_discrepancy(session, USER, transfer_id, disc_id,
                                    ResolveDiscrepancyRequest(resolution="RETURNED")),
    )
    problems = []
    if (status, code) != (409, "DISCREPANCY_ALREADY_RESOLVED"):
        problems.append(f"got {status} {code}")
    if not before == inside == after:
        problems.append(f"ledger rows {before}/{inside}/{after}")
    _report("S6", "second resolve of S1 -> 409 DISCREPANCY_ALREADY_RESOLVED", problems)


async def _s7(session, ctx: Ctx) -> None:
    transfer_id, disc_id = await _short_receipt(session, ctx, "DAMAGED")
    status, code, before, inside, after = await _expect_error(
        session, ctx.batch_product,
        lambda: resolve_discrepancy(session, USER, transfer_id, disc_id,
                                    ResolveDiscrepancyRequest(resolution="RETURNED")),
    )
    state = await _disc_state(session, disc_id)
    problems = []
    if (status, code) != (422, "RESOLUTION_NOT_ALLOWED"):
        problems.append(f"got {status} {code}")
    if not before == inside == after:
        problems.append(f"ledger rows {before}/{inside}/{after}")
    if state.status != "OPEN":
        problems.append(f"status {state.status}")
    _report("S7", "DAMAGED -> RETURNED: 422 RESOLUTION_NOT_ALLOWED, nothing written", problems)


async def _s8(session, ctx: Ctx) -> None:
    transfer_id, disc_id = await _short_receipt(session, ctx, "WRONG_LOT")
    # Leave lot B with 1 at SRC — less than N (4).
    lot_b_now = (await _lot_balances(session, ctx.batch_product, ctx.src))[ctx.lot_b]
    if lot_b_now > 1:
        await record_transaction(
            session, E2E_TENANT_ID, "ISSUE", ctx.batch_product, ctx.src, -(lot_b_now - 1),
            E2E_USER_ID, f"smoke:disc:issue:{uuid.uuid4()}", lot_id=ctx.lot_b, lot_number="LOT-B",
        )
    lot_b_set = (await _lot_balances(session, ctx.batch_product, ctx.src))[ctx.lot_b]
    status, code, before, inside, after = await _expect_error(
        session, ctx.batch_product,
        lambda: resolve_discrepancy(session, USER, transfer_id, disc_id,
                                    ResolveDiscrepancyRequest(resolution="RECEIVED_AS_LOT",
                                                              lot_id=uuid.UUID(ctx.lot_b))),
    )
    state = await _disc_state(session, disc_id)
    problems = []
    if lot_b_set >= N:
        problems.append(f"setup: lot B at SRC is {lot_b_set}, not below {N}")
    if status != 422:
        problems.append(f"got {status} {code}")
    if before != after:
        problems.append(f"ledger rows {before} -> {after} after the call")
    if state.status != "OPEN":
        problems.append(f"status {state.status}")
    print(f"     S8 detail: lot B at SRC = {lot_b_set}; error {status} {code}; "
          f"ledger rows before/inside/after = {before}/{inside}/{after}")
    _report("S8", "RECEIVED_AS_LOT with lot B < N at SRC: 422, ledger row count unchanged", problems)


async def _s9(session, ctx: Ctx) -> None:
    rm = _user("RM", ctx.dst)           # node is DST only — not PARENT
    t_late, d_late = await _short_receipt(session, ctx, "SHORT")
    t_ret, d_ret = await _short_receipt(session, ctx, "SHORT")
    problems = []
    try:
        out = await _resolve(session, ctx, rm, t_late, d_late, "ARRIVED_LATE")
        if out.status != "RESOLVED":
            problems.append(f"ARRIVED_LATE status {out.status}")
    except HTTPException as exc:
        problems.append(f"ARRIVED_LATE raised {exc.status_code} {exc.detail}")
    status, code, before, inside, after = await _expect_error(
        session, ctx.batch_product,
        lambda: resolve_discrepancy(session, rm, t_ret, d_ret,
                                    ResolveDiscrepancyRequest(resolution="RETURNED")),
    )
    if (status, code) != (403, "DISCREPANCY_OUT_OF_SCOPE"):
        problems.append(f"RETURNED got {status} {code}")
    if not before == inside == after:
        problems.append(f"ledger rows {before}/{inside}/{after}")
    _report("S9", "RM at DST only: ARRIVED_LATE OK, RETURNED -> 403 DISCREPANCY_OUT_OF_SCOPE", problems)


async def _s10(session, ctx: Ctx) -> None:
    mine = set(ctx.smoke_ids)

    async def ids(user, **kwargs) -> set[str]:
        return {str(i.id) for i in await list_discrepancies(session, user, **kwargs)}

    ta, wm_dst = await ids(_user("TA", None)), await ids(_user("WM", ctx.dst))
    wm_other, rm_parent = await ids(_user("WM", ctx.other)), await ids(_user("RM", ctx.parent))
    problems = []
    if not mine <= ta:
        problems.append(f"TA misses {len(mine - ta)} of {len(mine)}")
    if not mine <= wm_dst:
        problems.append(f"WM@DST misses {len(mine - wm_dst)}")
    if wm_other & mine:
        problems.append(f"WM@OTHER sees {len(wm_other & mine)}")
    if not mine <= rm_parent:
        problems.append(f"RM@PARENT misses {len(mine - rm_parent)}")
    try:
        await list_discrepancies(session, _user("WM", ctx.dst), warehouse_id=ctx.other)
        problems.append("WM@DST warehouse_id=OTHER did not raise")
    except HTTPException as exc:
        code = exc.detail.get("code") if isinstance(exc.detail, dict) else exc.detail
        if (exc.status_code, code) != (403, "WAREHOUSE_OUT_OF_SCOPE"):
            problems.append(f"WM@DST warehouse_id=OTHER got {exc.status_code} {code}")
    print(f"     S10 detail: smoke={len(mine)} TA={len(mine & ta)} WM@DST={len(mine & wm_dst)} "
          f"WM@OTHER={len(mine & wm_other)} (total listed {len(wm_other)}) RM@PARENT={len(mine & rm_parent)}")
    _report("S10", "list: TA/WM@DST/RM@PARENT see all, WM@OTHER none, WM@DST+OTHER -> 403", problems)


async def _s11(session, ctx: Ctx) -> None:
    rows = (await session.execute(
        text("SELECT resource_id::text AS rid, count(*) AS n FROM audit_logs "
             "WHERE tenant_id = :tid AND action = :action AND resource_id::text = ANY(:ids) "
             "GROUP BY resource_id::text"),
        {"tid": E2E_TENANT_ID, "action": AUDIT_ACTION, "ids": ctx.smoke_ids},
    )).fetchall()
    per_id = {r.rid: r.n for r in rows}
    problems = []
    for rid in ctx.resolved_ids:
        if per_id.get(rid) != 1:
            problems.append(f"{rid[:8]} has {per_id.get(rid, 0)} audit rows")
    unresolved = [rid for rid in per_id if rid not in ctx.resolved_ids]
    if unresolved:
        problems.append(f"{len(unresolved)} audit rows for unresolved discrepancies")
    print(f"     S11 detail: successful resolves={len(ctx.resolved_ids)} audit rows={sum(per_id.values())}")
    _report("S11", "audit_logs: exactly one transfer:resolve_discrepancy row per successful resolve", problems)


async def _s12(session, ctx: Ctx) -> None:
    problems, parts = [], []
    for label, wh in (("SRC", ctx.src), ("DST", ctx.dst)):
        balance = await _product_balance(session, ctx.batch_product, wh)
        lots = sum((await _lot_balances(session, ctx.batch_product, wh)).values(), Decimal("0"))
        parts.append(f"{label} inventory_balances={balance} sum(lot_balances)={lots}")
        if balance != lots:
            problems.append(f"{label} {balance} != {lots}")
    _report("S12", "invariant inventory_balances == SUM(lot_balances): " + "; ".join(parts), problems)


# ── fixtures and driver ──────────────────────────────────────────────────────

async def _node(session, name: str, code: str, level: int, parent: Optional[str], stock: bool) -> str:
    node_id = str(uuid.uuid4())
    await session.execute(
        text(
            "INSERT INTO organization_node "
            "(id, tenant_id, name, code, hierarchy_level, parent_node_id, is_stock_holding, is_active) "
            "VALUES (:id, :tid, :name, :code, :level, :parent, :stock, true)"
        ),
        {"id": node_id, "tid": E2E_TENANT_ID, "name": name, "code": code,
         "level": level, "parent": parent, "stock": stock},
    )
    return node_id


async def _run(session, suffix: str) -> None:
    await set_rls_context(session, E2E_TENANT_ID, E2E_USER_ID)

    parent = await _node(session, f"Smoke Disc Parent {suffix}", f"SMOKE-DP-{suffix}", 1, None, False)
    src = await _node(session, f"Smoke Disc Source {suffix}", f"SMOKE-DS-{suffix}", 2, parent, True)
    dst = await _node(session, f"Smoke Disc Dest {suffix}", f"SMOKE-DD-{suffix}", 2, parent, True)
    other = await _node(session, f"Smoke Disc Other {suffix}", f"SMOKE-DO-{suffix}", 1, None, True)
    print(f"     parent={parent[:8]} src={src[:8]} dst={dst[:8]} other={other[:8]}")

    ctx = Ctx(InventoryService(session), parent, src, dst, other)
    ctx.batch_product = await _make_product(session, suffix, "D", batch=True)
    ctx.plain_product = await _make_product(session, suffix, "P", batch=False)
    ctx.lot_a = await _stock(session, ctx.batch_product, src, "10", "LOT-A", 30)
    ctx.lot_b = await _stock(session, ctx.batch_product, src, "10", "LOT-B", 60)
    await _stock(session, ctx.plain_product, src, "50")

    try:
        for scenario in (_s1, _s2, _s3, _s4, _s5, _s6, _s7, _s8, _s9, _s10, _s11, _s12):
            try:
                await scenario(session, ctx)
            except Exception:
                traceback.print_exc()
                _results.append(False)
                print(f"FAIL {scenario.__name__.strip('_').upper()}  unexpected exception (traceback above) — stopping")
                return
    finally:
        ctx_ids.extend(ctx.smoke_ids)


ctx_ids: list[str] = []


async def main() -> int:
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        try:
            await _run(session, suffix)
        except Exception:
            traceback.print_exc()
            _results.append(False)
            print("FAIL setup/unexpected exception (see traceback above)")
        finally:
            # never commit
            await session.rollback()
            print("ROLLED BACK")

    # post-rollback check from a NEW session
    async with AsyncSessionLocal() as verify:
        await set_rls_context(verify, E2E_TENANT_ID, E2E_USER_ID)
        counts = {}
        for label, sql, params in (
            ("products", "SELECT count(*) FROM products WHERE tenant_id = :tid AND sku LIKE :p",
             {"p": f"SMKR-%-{suffix}"}),
            ("nodes", "SELECT count(*) FROM organization_node WHERE tenant_id = :tid AND code LIKE :p",
             {"p": f"SMOKE-D_-{suffix}"}),
            ("discrepancies", "SELECT count(*) FROM transfer_discrepancies d JOIN products p ON p.id = d.product_id "
             "WHERE d.tenant_id = :tid AND p.sku LIKE :p", {"p": f"SMKR-%-{suffix}"}),
            ("audit rows", "SELECT count(*) FROM audit_logs WHERE tenant_id = :tid AND action = :a "
             "AND resource_id::text = ANY(:ids)", {"a": AUDIT_ACTION, "ids": ctx_ids or [""]}),
        ):
            counts[label] = (await verify.execute(text(sql), {"tid": E2E_TENANT_ID, **params})).scalar()
        await verify.rollback()
    clean = all(v == 0 for v in counts.values())
    print(f"post-rollback leftovers: {counts}")

    passed, total = sum(_results), len(_results)
    expected_total = 12
    ok = passed == total == expected_total and clean
    print(f"SMOKE discrepancy_resolution: {passed}/{expected_total} PASS — "
          + ("rolled back" if clean else "ROLLBACK CHECK FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
