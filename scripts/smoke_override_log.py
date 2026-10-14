"""Rollback-only real-DB smoke check for the lot override log and FEFO compliance
summary (services/override_log_service.py: list_overrides, override_summary).

Opens ONE async session against DATABASE_URL and NEVER commits — everything
happens inside one transaction that is rolled back in a `finally` block, so it is
safe to run against a real database with no cleanup step.

Fixtures are built the way real tenants are: an existing stock-holding
organization_node, never the legacy `warehouses` table. In the transaction it
creates a batch/expiry product with two lots, inserts one ISSUE override row
(shape from dispatch_service.record_override), then reads the log and the
summary as a TA-like user of that tenant and as a user of ANOTHER tenant.

Usage:
    set -a; source .env; set +a
    python scripts/smoke_override_log.py
"""
from __future__ import annotations

import asyncio
import json
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
from services.lot_settings_service import update_lot_settings  # noqa: E402
from services.override_log_service import list_overrides, override_summary  # noqa: E402


def _ok(label: str) -> None:
    print(f"OK   {label}")


def _assert(cond: bool, label: str) -> None:
    if not cond:
        raise AssertionError(f"FAILED: {label}")
    _ok(label)


async def main() -> None:
    suffix = uuid.uuid4().hex[:8]
    sku = f"SMKO-{suffix}"
    tenant_id = uid = None
    async with AsyncSessionLocal() as session:
        try:
            # a) a tenant with a stock-holding organization_node, a user of it, and
            #    a user of another tenant
            node = (await session.execute(text(
                "SELECT n.tenant_id, n.id, n.name FROM organization_node n "
                "WHERE n.is_stock_holding AND n.is_active "
                "  AND EXISTS (SELECT 1 FROM users u WHERE u.tenant_id = n.tenant_id AND u.is_active) "
                "ORDER BY n.created_at LIMIT 1"
            ))).fetchone()
            _assert(node is not None, "found a tenant with a stock-holding organization_node")
            tenant_id, wh, wh_name = str(node.tenant_id), str(node.id), node.name
            uid = str((await session.execute(
                text("SELECT id FROM users WHERE tenant_id = :t AND is_active ORDER BY created_at LIMIT 1"),
                {"t": tenant_id},
            )).fetchone().id)
            other = (await session.execute(
                text(
                    "SELECT t.id AS tid, u.id AS uid FROM tenants t "
                    "JOIN users u ON u.tenant_id = t.id AND u.is_active "
                    "WHERE t.id <> :t AND t.is_active ORDER BY t.created_at LIMIT 1"
                ),
                {"t": tenant_id},
            )).fetchone()
            _assert(other is not None, "found a user of another tenant")
            other_tid, other_uid = str(other.tid), str(other.uid)
            print(f"tenant {tenant_id} node {wh_name!r}; other tenant {other_tid}")

            await set_rls_context(session, tenant_id, uid)
            user = SimpleNamespace(user_id=uid, role="TA", tenant_id=tenant_id, warehouse_id=None)
            print("audit: update_lot_settings writes audit_logs in the same transaction (rolled back)")

            # b) batch + expiry product (FEFO) with two lots in that warehouse
            product_id = str(uuid.uuid4())
            await session.execute(
                text(
                    "INSERT INTO products "
                    "(id, tenant_id, sku, name, unit_of_measure, batch_tracking, expiry_tracking, is_active) "
                    "VALUES (:id, :tid, :sku, :name, 'EACH', false, false, true)"
                ),
                {"id": product_id, "tid": tenant_id, "sku": sku,
                 "name": f"Smoke Override Product {suffix}"},
            )
            await record_transaction(
                session, tenant_id, "RECEIVE", product_id, wh, Decimal("10"),
                uid, f"smoke:receive:{product_id}:{uuid.uuid4()}", source="OPENING_BALANCE",
            )
            result = await update_lot_settings(
                session, tenant_id=tenant_id, product_id=product_id, user_id=uid,
                role="TA", feature_enabled=True, batch_tracking=True, expiry_tracking=True,
                dispatch_strategy=None,
            )
            _assert(len(result.opening_lots) == 1, "conversion created one OPENING lot")
            lot_a = str(result.opening_lots[0].lot_id)
            lot_a_number = result.opening_lots[0].lot_number
            lot_b = str(uuid.uuid4())
            lot_b_number = f"SMK-B-{suffix}"
            await session.execute(
                text(
                    "INSERT INTO stock_lots (id, tenant_id, product_id, lot_number, created_by) "
                    "VALUES (:id, :tid, :pid, :num, :uid)"
                ),
                {"id": lot_b, "tid": tenant_id, "pid": product_id, "num": lot_b_number, "uid": uid},
            )
            _ok(f"two lots: {lot_a_number} (suggested) and {lot_b_number} (chosen)")

            # c) one ISSUE override row, suggested/chosen in record_override's JSON shape
            override_id = str(uuid.uuid4())
            issue_ref = str(uuid.uuid4())
            suggested = [{"lot_id": lot_a, "lot_number": lot_a_number, "quantity": "2"}]
            chosen = [{"lot_id": lot_b, "lot_number": lot_b_number, "quantity": "2"}]
            await session.execute(
                text(
                    "INSERT INTO lot_allocation_overrides "
                    "(id, tenant_id, product_id, warehouse_id, strategy, movement_type, reference_id, "
                    " requested_qty, suggested, chosen, reason, overridden_by) "
                    "VALUES (:id, :tid, :pid, :wid, CAST('FEFO' AS dispatch_strategy), 'ISSUE', :ref, "
                    "        2, CAST(:suggested AS jsonb), CAST(:chosen AS jsonb), 'smoke', :uid)"
                ),
                {"id": override_id, "tid": tenant_id, "pid": product_id, "wid": wh,
                 "ref": issue_ref, "suggested": json.dumps(suggested), "chosen": json.dumps(chosen),
                 "uid": uid},
            )

            # c2) the matching ISSUE ledger rows, as inventory_service.issue posts them:
            #     the chosen lot, reference_id = the override's issue_ref (lot_b needs
            #     stock first, so it is received in this transaction)
            await record_transaction(
                session, tenant_id, "RECEIVE", product_id, wh, Decimal("2"),
                uid, f"smoke:receive-b:{product_id}:{uuid.uuid4()}",
                lot_id=lot_b, lot_number=lot_b_number, source="OPENING_BALANCE",
            )
            await record_transaction(
                session, tenant_id, "ISSUE", product_id, wh, Decimal("-2"),
                uid, f"smoke:issue:{issue_ref}:lot:{lot_b}",
                reference_id=issue_ref, lot_id=lot_b, lot_number=lot_b_number,
            )

            # d) the log, as a TA-like user of the tenant
            log = await list_overrides(session, user, tenant_id, product_id=product_id)
            mine = [r for r in log.rows if str(r.id) == override_id]
            _assert(log.total == 1 and len(mine) == 1, "list_overrides lists the override row")
            row = mine[0]
            _assert(
                [x.lot_number for x in row.suggested] == [lot_a_number]
                and [x.lot_number for x in row.chosen] == [lot_b_number],
                f"row carries lot numbers (suggested {lot_a_number}, chosen {lot_b_number})",
            )
            _assert(row.warehouse.name == wh_name, "warehouse name comes from organization_node")
            _assert(row.product.sku == sku and row.strategy == "FEFO"
                    and row.movement_type == "ISSUE" and row.reason == "smoke",
                    "row carries product sku, strategy, movement type and reason")
            _assert(bool(row.overridden_by), f"overridden_by resolved to a name ({row.overridden_by!r})")

            # e) the summary
            summary = await override_summary(session, user, tenant_id, warehouse_id=wh)
            print(f"summary: {summary.model_dump_json()}")
            _assert(summary.overall.overridden >= 1, "summary overall.overridden >= 1")
            _assert(summary.fefo.overridden >= 1, "summary fefo.overridden >= 1 (product is FEFO)")
            _assert(summary.by_movement["ISSUE"].overridden >= 1, "summary by_movement ISSUE.overridden >= 1")
            issue_c = summary.by_movement["ISSUE"]
            _assert(issue_c.overridden <= issue_c.decisions,
                    "summary ISSUE.overridden <= ISSUE.decisions (same ledger set)")
            # a period ending before today holds none of the ledger rows -> not counted
            past = date.today() - timedelta(days=60)
            old = await override_summary(
                session, user, tenant_id, date_from=past - timedelta(days=5), date_to=past,
                warehouse_id=wh,
            )
            _assert(old.by_movement["ISSUE"].overridden == 0,
                    "an override whose ledger rows are outside the period is not counted")

            # f) another tenant never sees it
            await set_rls_context(session, other_tid, other_uid)
            other_user = SimpleNamespace(
                user_id=other_uid, role="TA", tenant_id=other_tid, warehouse_id=None
            )
            other_log = await list_overrides(session, other_user, other_tid)
            _assert(all(str(r.id) != override_id for r in other_log.rows),
                    "another tenant's log does not contain the row")
            other_by_product = await list_overrides(
                session, other_user, other_tid, product_id=product_id
            )
            _assert(other_by_product.total == 0 and other_by_product.rows == [],
                    "another tenant, filtering by this product: nothing")
            print("SMOKE PASS")
        finally:
            await session.rollback()

    # g) post-rollback check from a NEW session
    async with AsyncSessionLocal() as verify_session:
        await set_rls_context(verify_session, tenant_id, uid)
        row = (await verify_session.execute(
            text("SELECT id FROM products WHERE sku = :sku"), {"sku": sku},
        )).fetchone()
        print(f"Post-rollback check: product {'is gone (expected)' if row is None else 'STILL PRESENT'}")
        await verify_session.rollback()
        if row is not None:
            raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
