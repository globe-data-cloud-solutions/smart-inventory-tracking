"""Rollback-only real-DB smoke check for the batch-tracking conversion added in
a501b81 (update_lot_settings / create_opening_lot / LOT_OPENING).

Opens ONE async session against DATABASE_URL, sets the RLS context for the
permanent zz-e2e-ta tenant, and NEVER commits — everything happens inside one
transaction that is rolled back in a `finally` block, so it is safe to run
against a real database with no cleanup step.

Usage:
    set -a; source .env; set +a
    python scripts/smoke_lot_conversion.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
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
from repositories.lot_repo import lot_totals_mismatch  # noqa: E402
from services.lot_settings_service import update_lot_settings  # noqa: E402

E2E_TENANT_ID = "5e60ea08-d596-4a46-b63e-ddd7c373f3f0"
E2E_USER_ID = "e05c6e17-1d3c-45f8-9da3-12000b461868"


def _ok(label: str) -> None:
    print(f"OK   {label}")


def _assert(cond: bool, label: str) -> None:
    if not cond:
        raise AssertionError(f"FAILED: {label}")
    _ok(label)


async def main() -> None:
    async with AsyncSessionLocal() as session:
        try:
            await set_rls_context(session, E2E_TENANT_ID, E2E_USER_ID)

            # ── pick/create a non-batch product with on-hand stock in 2 warehouses ──
            suffix = uuid.uuid4().hex[:8]
            wh1 = str(uuid.uuid4())
            wh2 = str(uuid.uuid4())
            await session.execute(
                text(
                    "INSERT INTO warehouses (id, tenant_id, name, code, is_active) "
                    "VALUES (:id, :tid, :name, :code, true)"
                ),
                {
                    "id": wh1,
                    "tid": E2E_TENANT_ID,
                    "name": f"Smoke WH1 {suffix}",
                    "code": f"SMK1{suffix}",
                },
            )
            await session.execute(
                text(
                    "INSERT INTO warehouses (id, tenant_id, name, code, is_active) "
                    "VALUES (:id, :tid, :name, :code, true)"
                ),
                {
                    "id": wh2,
                    "tid": E2E_TENANT_ID,
                    "name": f"Smoke WH2 {suffix}",
                    "code": f"SMK2{suffix}",
                },
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
                    "sku": f"SMK-{suffix}",
                    "name": f"Smoke Product {suffix}",
                },
            )

            for wh in (wh1, wh2):
                await record_transaction(
                    session,
                    E2E_TENANT_ID,
                    "RECEIVE",
                    product_id,
                    wh,
                    Decimal("10"),
                    E2E_USER_ID,
                    f"smoke:receive:{product_id}:{wh}:{uuid.uuid4()}",
                    source="OPENING_BALANCE",
                )

            balances_before = (
                await session.execute(
                    text(
                        "SELECT warehouse_id, quantity FROM inventory_balances "
                        "WHERE tenant_id = :tid AND product_id = :pid AND lot_number IS NULL"
                    ),
                    {"tid": E2E_TENANT_ID, "pid": product_id},
                )
            ).fetchall()
            print(
                f"Per-warehouse balances before conversion: {[(str(r.warehouse_id), str(r.quantity)) for r in balances_before]}"
            )
            _assert(
                len(balances_before) == 2,
                "two warehouses have on-hand stock before conversion",
            )

            # ── call the lot-settings service function: batch on, expiry off, strategy null ──
            result = await update_lot_settings(
                session,
                tenant_id=E2E_TENANT_ID,
                product_id=product_id,
                user_id=E2E_USER_ID,
                role="TA",
                feature_enabled=True,
                batch_tracking=True,
                expiry_tracking=False,
                dispatch_strategy=None,
            )

            _assert(
                result.batch_tracking is True, "batch_tracking is True after conversion"
            )
            _assert(
                result.expiry_tracking is False,
                "expiry_tracking is False after conversion",
            )
            _assert(
                result.dispatch_strategy == "FIFO",
                "dispatch_strategy defaulted to FIFO",
            )
            _assert(
                len(result.opening_lots) == 2, "one opening lot per stocked warehouse"
            )
            print(
                f"Opening lots: {[(ol.lot_number, str(ol.quantity)) for ol in result.opening_lots]}"
            )

            lot_rows = (
                await session.execute(
                    text(
                        "SELECT id, lot_number, is_opening, expiry_date FROM stock_lots "
                        "WHERE tenant_id = :tid AND product_id = :pid"
                    ),
                    {"tid": E2E_TENANT_ID, "pid": product_id},
                )
            ).fetchall()
            _assert(len(lot_rows) == 2, "exactly two stock_lots rows created")
            _assert(all(r.is_opening for r in lot_rows), "all lots are is_opening")
            _assert(
                all(r.expiry_date is None for r in lot_rows),
                "all lots have NULL expiry",
            )
            _assert(
                all(r.lot_number.startswith("OPENING-") for r in lot_rows),
                "lot numbers start with OPENING-",
            )

            lot_balances = (
                await session.execute(
                    text(
                        "SELECT lot_id, warehouse_id, quantity FROM lot_balances "
                        "WHERE tenant_id = :tid AND product_id = :pid"
                    ),
                    {"tid": E2E_TENANT_ID, "pid": product_id},
                )
            ).fetchall()
            _assert(len(lot_balances) == 2, "two lot_balances rows")
            _assert(
                all(Decimal(str(r.quantity)) == Decimal("10") for r in lot_balances),
                "lot_balances equal the on-hand per warehouse",
            )

            balances_after = (
                await session.execute(
                    text(
                        "SELECT warehouse_id, quantity FROM inventory_balances "
                        "WHERE tenant_id = :tid AND product_id = :pid AND lot_number IS NULL"
                    ),
                    {"tid": E2E_TENANT_ID, "pid": product_id},
                )
            ).fetchall()
            before_map = {str(r.warehouse_id): r.quantity for r in balances_before}
            after_map = {str(r.warehouse_id): r.quantity for r in balances_after}
            _assert(
                before_map == after_map,
                "inventory_balances UNCHANGED by the conversion",
            )

            ledger_rows = (
                await session.execute(
                    text(
                        "SELECT warehouse_id, lot_id FROM inventory_transactions "
                        "WHERE tenant_id = :tid AND product_id = :pid AND type = 'LOT_OPENING'"
                    ),
                    {"tid": E2E_TENANT_ID, "pid": product_id},
                )
            ).fetchall()
            _assert(len(ledger_rows) == 2, "one LOT_OPENING ledger row per lot")

            for wh in (wh1, wh2):
                mismatch = await lot_totals_mismatch(
                    session, E2E_TENANT_ID, product_id, wh
                )
                _assert(
                    mismatch is None, f"lot_totals_mismatch empty for warehouse {wh}"
                )

            product_row = (
                await session.execute(
                    text(
                        "SELECT dispatch_strategy FROM products WHERE id = :pid AND tenant_id = :tid"
                    ),
                    {"pid": product_id, "tid": E2E_TENANT_ID},
                )
            ).fetchone()
            _assert(
                product_row.dispatch_strategy == "FIFO",
                "products.dispatch_strategy = FIFO",
            )

            opening_lot_id = str(lot_balances[0].lot_id)
            opening_wh = str(lot_balances[0].warehouse_id)

            # ── ISSUE without lot_id -> 422 LOT_REQUIRED (inside a SAVEPOINT) ──
            try:
                async with session.begin_nested():
                    await record_transaction(
                        session,
                        E2E_TENANT_ID,
                        "ISSUE",
                        product_id,
                        opening_wh,
                        Decimal("-1"),
                        E2E_USER_ID,
                        f"smoke:issue-no-lot:{product_id}:{uuid.uuid4()}",
                        source="WEB",
                    )
                    raise AssertionError(
                        "FAILED: expected LOT_REQUIRED, record_transaction succeeded"
                    )
            except AssertionError:
                raise
            except Exception as exc:
                code = (
                    getattr(exc, "detail", {}).get("code")
                    if hasattr(exc, "detail")
                    else None
                )
                _assert(
                    code == "LOT_REQUIRED",
                    f"ISSUE without lot_id raised LOT_REQUIRED (got {code!r})",
                )

            # ── ISSUE with the opening lot_id -> ok ──
            await record_transaction(
                session,
                E2E_TENANT_ID,
                "ISSUE",
                product_id,
                opening_wh,
                Decimal("-1"),
                E2E_USER_ID,
                f"smoke:issue-with-lot:{product_id}:{uuid.uuid4()}",
                lot_id=opening_lot_id,
                source="WEB",
            )

            product_balance_row = (
                await session.execute(
                    text(
                        "SELECT quantity FROM inventory_balances "
                        "WHERE tenant_id = :tid AND product_id = :pid AND warehouse_id = :wid AND lot_number IS NULL"
                    ),
                    {"tid": E2E_TENANT_ID, "pid": product_id, "wid": opening_wh},
                )
            ).fetchone()
            lot_balance_row = (
                await session.execute(
                    text(
                        "SELECT quantity FROM lot_balances "
                        "WHERE tenant_id = :tid AND lot_id = :lid AND warehouse_id = :wid"
                    ),
                    {"tid": E2E_TENANT_ID, "lid": opening_lot_id, "wid": opening_wh},
                )
            ).fetchone()
            print(
                f"After ISSUE -1: product balance={product_balance_row.quantity}, "
                f"lot balance={lot_balance_row.quantity}"
            )
            _assert(
                Decimal(str(product_balance_row.quantity)) == Decimal("9"),
                "product balance down by 1",
            )
            _assert(
                Decimal(str(lot_balance_row.quantity)) == Decimal("9"),
                "lot balance down by 1",
            )

            # ── batch off -> expect 409 BATCH_TRACKING_IN_USE ──
            try:
                await update_lot_settings(
                    session,
                    tenant_id=E2E_TENANT_ID,
                    product_id=product_id,
                    user_id=E2E_USER_ID,
                    role="TA",
                    feature_enabled=True,
                    batch_tracking=False,
                    expiry_tracking=False,
                    dispatch_strategy=None,
                )
                raise AssertionError("FAILED: expected BATCH_TRACKING_IN_USE")
            except Exception as exc:
                code = (
                    getattr(exc, "detail", {}).get("code")
                    if hasattr(exc, "detail")
                    else None
                )
                _assert(
                    code == "BATCH_TRACKING_IN_USE",
                    f"batch off raised BATCH_TRACKING_IN_USE (got {code!r})",
                )

            print("SMOKE PASS")
        finally:
            await session.rollback()

    # ── post-rollback check from a NEW session ──
    async with AsyncSessionLocal() as verify_session:
        await set_rls_context(verify_session, E2E_TENANT_ID, E2E_USER_ID)
        row = (
            await verify_session.execute(
                text(
                    "SELECT batch_tracking FROM products WHERE tenant_id = :tid AND sku = :sku"
                ),
                {"tid": E2E_TENANT_ID, "sku": f"SMK-{suffix}"},
            )
        ).fetchone()
        print(
            f"Post-rollback check: product {'not found (expected)' if row is None else f'batch_tracking={row.batch_tracking}'}"
        )
        await verify_session.rollback()


if __name__ == "__main__":
    asyncio.run(main())
