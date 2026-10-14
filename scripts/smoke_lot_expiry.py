"""Rollback-only real-DB smoke check for FEFO phase D1: the lot list warehouse
join fix, GET expiry alerts, and set_lot_expiry (set an expiry once).

Opens ONE async session against DATABASE_URL, sets the RLS context for the
permanent zz-e2e-ta tenant, and NEVER commits — everything happens inside one
transaction that is rolled back in a `finally` block, so it is safe to run
against a real database with no cleanup step.

The tenant has no organization_node rows, so the script creates one (plus the
matching legacy `warehouses` row that update_lot_settings joins) with the same
id inside the transaction.

Usage:
    set -a; source .env; set +a
    python scripts/smoke_lot_expiry.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import date, timedelta
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
from services.inventory_analytics import get_expiry_alerts, get_lots  # noqa: E402
from services.lot_expiry_service import set_lot_expiry  # noqa: E402
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
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        try:
            await set_rls_context(session, E2E_TENANT_ID, E2E_USER_ID)
            tid = uuid.UUID(E2E_TENANT_ID)
            user = SimpleNamespace(user_id=E2E_USER_ID, role="TA", tenant_id=E2E_TENANT_ID)
            # set_lot_expiry audits with an INSERT in this same session/transaction
            # (like lot_settings_service), so the rollback removes it.
            print("audit: set_lot_expiry writes audit_logs in the same transaction (rolled back)")

            # a) product with stock in a stock-holding org-node warehouse, converted
            wh = str(uuid.uuid4())
            wh_name = f"Smoke Expiry WH {suffix}"
            await session.execute(
                text(
                    "INSERT INTO organization_node "
                    "(id, tenant_id, name, code, hierarchy_level, is_stock_holding, is_active) "
                    "VALUES (:id, :tid, :name, :code, 1, true, true)"
                ),
                {"id": wh, "tid": E2E_TENANT_ID, "name": wh_name, "code": f"SXP{suffix}"},
            )
            await session.execute(
                text(
                    "INSERT INTO warehouses (id, tenant_id, name, code, is_active) "
                    "VALUES (:id, :tid, :name, :code, true)"
                ),
                {"id": wh, "tid": E2E_TENANT_ID, "name": wh_name, "code": f"SXP{suffix}"},
            )
            product_id = str(uuid.uuid4())
            await session.execute(
                text(
                    "INSERT INTO products "
                    "(id, tenant_id, sku, name, unit_of_measure, batch_tracking, expiry_tracking, is_active) "
                    "VALUES (:id, :tid, :sku, :name, 'EACH', false, false, true)"
                ),
                {"id": product_id, "tid": E2E_TENANT_ID, "sku": f"SMKX-{suffix}",
                 "name": f"Smoke Expiry Product {suffix}"},
            )
            await record_transaction(
                session, E2E_TENANT_ID, "RECEIVE", product_id, wh, Decimal("10"),
                E2E_USER_ID, f"smoke:receive:{product_id}:{uuid.uuid4()}", source="OPENING_BALANCE",
            )
            result = await update_lot_settings(
                session, tenant_id=E2E_TENANT_ID, product_id=product_id, user_id=E2E_USER_ID,
                role="TA", feature_enabled=True, batch_tracking=True, expiry_tracking=True,
                dispatch_strategy=None,
            )
            _assert(len(result.opening_lots) == 1, "conversion created one OPENING lot")
            lot_id = str(result.opening_lots[0].lot_id)
            lot_number = result.opening_lots[0].lot_number

            # b) lot list: lot present, warehouse_name non-empty (join fix)
            lots = await get_lots(session, tid, product_id=uuid.UUID(product_id))
            mine = [lot for lot in lots if str(lot.lot_id) == lot_id]
            _assert(len(mine) == 1, "get_lots lists the OPENING lot")
            print(f"warehouse_name from get_lots: {mine[0].warehouse_name!r}")
            _assert(bool(mine[0].warehouse_name), "get_lots warehouse_name is non-empty")
            _assert(mine[0].warehouse_name == wh_name, "warehouse_name comes from organization_node")
            _assert(mine[0].expiry_date is None, "lot has no expiry yet")

            # c) alerts: NO_EXPIRY
            alerts = await get_expiry_alerts(session, tid)
            a = [i for i in alerts.items if str(i.lot_id) == lot_id]
            _assert(len(a) == 1 and a[0].alert_type == "NO_EXPIRY", "expiry alerts list the lot as NO_EXPIRY")

            # d) set expiry today + 10
            exp = date.today() + timedelta(days=10)
            out = await set_lot_expiry(session, E2E_TENANT_ID, lot_id, exp, user)
            _assert(out["expiry_date"] == exp and str(out["lot_id"]) == lot_id, "set_lot_expiry succeeded")

            # e) alerts: EXPIRING 10; lot list: expiring_soon, ACTIVE
            alerts = await get_expiry_alerts(session, tid)
            a = [i for i in alerts.items if str(i.lot_id) == lot_id]
            _assert(
                len(a) == 1 and a[0].alert_type == "EXPIRING" and a[0].days_to_expiry == 10,
                "expiry alerts now EXPIRING with days_to_expiry 10",
            )
            lots = await get_lots(session, tid, product_id=uuid.UUID(product_id))
            mine_lot = [lot for lot in lots if str(lot.lot_id) == lot_id][0]
            _assert(
                mine_lot.expiring_soon is True and mine_lot.status == "ACTIVE",
                "get_lots expiring_soon true, status ACTIVE",
            )

            # f) second set -> 409
            try:
                await set_lot_expiry(session, E2E_TENANT_ID, lot_id, exp + timedelta(days=1), user)
                raise AssertionError("FAILED: expected LOT_EXPIRY_ALREADY_SET")
            except AssertionError:
                raise
            except Exception as exc:
                detail = getattr(exc, "detail", {}) or {}
                _assert(
                    getattr(exc, "status_code", None) == 409
                    and detail.get("code") == "LOT_EXPIRY_ALREADY_SET"
                    and detail.get("existing_expiry") == exp.isoformat(),
                    f"second set_lot_expiry raised 409 LOT_EXPIRY_ALREADY_SET (got {detail!r})",
                )

            # set_lot_expiry must not touch the ledger
            n = (await session.execute(
                text("SELECT count(*) AS n FROM inventory_transactions "
                     "WHERE tenant_id = :tid AND product_id = :pid"),
                {"tid": E2E_TENANT_ID, "pid": product_id},
            )).fetchone().n
            _assert(n == 2, f"ledger holds only RECEIVE + LOT_OPENING for the product (got {n})")
            print(f"lot {lot_number} expiry set to {exp.isoformat()}")
            print("SMOKE PASS")
        finally:
            await session.rollback()

    # h) post-rollback check from a NEW session
    async with AsyncSessionLocal() as verify_session:
        await set_rls_context(verify_session, E2E_TENANT_ID, E2E_USER_ID)
        row = (await verify_session.execute(
            text("SELECT id FROM products WHERE tenant_id = :tid AND sku = :sku"),
            {"tid": E2E_TENANT_ID, "sku": f"SMKX-{suffix}"},
        )).fetchone()
        print(f"Post-rollback check: product {'not found (expected)' if row is None else 'STILL PRESENT'}")
        await verify_session.rollback()
        if row is not None:
            raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
