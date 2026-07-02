"""
delete_tenant.py — Reusable tenant purge script.

Deletes ALL data for one or more tenants from the database, handling:
  - PostgreSQL RLS — bypassed with SET LOCAL row_security = off (requires superuser
    or a role with BYPASSRLS attribute on the connecting user). Falls back to setting
    app.current_tenant_id if the DB user lacks BYPASSRLS.
  - Append-only RULE tables (audit_logs, tenant_activity_log) — the DELETE-blocking
    rules are dropped at the start of the transaction and recreated before commit.
  - FK ordering — child rows before parent rows; no cascades assumed.
  - Partitioned table (inventory_transactions) — deleted by tenant_id directly.
  - inventory_transaction_keys has no tenant_id — deleted via subquery join.

Usage:
    # Dry-run (shows row counts, no changes):
    python scripts/delete_tenant.py --dry-run "Tenant 01" "T2" "T03"

    # Live deletion — prompts for YES confirmation:
    python scripts/delete_tenant.py "Tenant 01" "T2" "T03"

    # By UUID:
    python scripts/delete_tenant.py --id a1b2c3d4-0000-0000-0000-000000000001

Requires: DATABASE_URL env var. The connecting user must have DELETE privileges on
all tables and ideally BYPASSRLS (or be the table owner) to skip RLS.

SAFE: Tenant 6 (Tenant_6_P2T) and Tenant 07 are excluded even if accidentally passed.
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from sqlalchemy import create_engine, text

# ---------------------------------------------------------------------------
# Connection — sync driver
# ---------------------------------------------------------------------------
_raw_url = os.environ["DATABASE_URL"]
_sync_url = (
    _raw_url
    .replace("postgresql+asyncpg://", "postgresql://")
    .replace("postgresql+psycopg2://", "postgresql://")
)
engine = create_engine(_sync_url, echo=False)

# ---------------------------------------------------------------------------
# Safety guard — never delete these tenants regardless of input
# ---------------------------------------------------------------------------
PROTECTED_TENANT_NAMES = {"tenant_6_p2t", "tenant 6", "t6", "tenant_07", "tenant 07", "t7"}

# ---------------------------------------------------------------------------
# Deletion order — children before parents, FK-safe.
# Each entry: (table_name, where_clause_template)
#   :tid is always the tenant UUID.
#   "__subquery__" means inventory_transaction_keys (no tenant_id column).
# ---------------------------------------------------------------------------
TENANT_TABLES: list[tuple[str, str]] = [
    # Append-only tables — rules are dropped/recreated around these
    ("audit_logs",                      "tenant_id = :tid"),
    ("tenant_activity_log",             "tenant_id = :tid"),
    # Outbox
    ("outbox",                          "tenant_id = :tid"),
    # Inventory ledger
    ("inventory_transaction_keys",      "__subquery__"),   # no tenant_id; subquery below
    ("inventory_transactions",          "tenant_id = :tid"),
    ("inventory_balances",              "tenant_id = :tid"),
    ("dispatch_strategy_configs",       "tenant_id = :tid"),
    ("dispatch_override_logs",          "tenant_id = :tid"),
    # Transfer workflow
    ("transfer_order_lines",            "tenant_id = :tid"),
    ("transfer_orders",                 "tenant_id = :tid"),
    ("transfer_requests",               "tenant_id = :tid"),
    ("count_sessions",                  "tenant_id = :tid"),
    ("adjustment_orders",               "tenant_id = :tid"),
    # Approval
    ("approval_rule",                   "tenant_id = :tid"),
    # Transfer type configuration
    ("transfer_type_level_permissions", "tenant_id = :tid"),
    ("transfer_type_config",            "tenant_id = :tid"),
    # Personnel & positions
    ("personnel_positions",             "tenant_id = :tid"),
    ("positions",                       "tenant_id = :tid"),
    # Products
    ("products",                        "tenant_id = :tid"),
    ("product_categories",              "tenant_id = :tid"),
    # Organisation hierarchy
    ("org_node_hierarchy",              "tenant_id = :tid"),
    ("organization_node",               "tenant_id = :tid"),
    ("tenant_hierarchy_config",         "tenant_id = :tid"),
    # Legacy flat warehouses model
    ("warehouses",                      "tenant_id = :tid"),
    # Users
    ("users",                           "tenant_id = :tid"),
    # Contacts & activity
    ("tenant_contacts",                 "tenant_id = :tid"),
    # Root tenant row — must be last
    ("tenants",                         "id = :tid"),
]

# SQL for the special subquery case
_ITK_DELETE = (
    "DELETE FROM inventory_transaction_keys "
    "WHERE transaction_id IN "
    "(SELECT id FROM inventory_transactions WHERE tenant_id = :tid)"
)
_ITK_COUNT = (
    "SELECT COUNT(*) FROM inventory_transaction_keys "
    "WHERE transaction_id IN "
    "(SELECT id FROM inventory_transactions WHERE tenant_id = :tid)"
)

# Append-only tables: rule name -> table (DROP the delete-blocking rule to allow purge)
APPEND_ONLY_DELETE_RULES: list[tuple[str, str]] = [
    ("no_delete_audit", "audit_logs"),
    ("no_delete_tal",   "tenant_activity_log"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_tenant_context(conn, tid: str) -> None:
    """
    Set app.current_tenant_id so RLS policies evaluate TRUE for this tenant's rows.
    Required for tables with FORCE ROW LEVEL SECURITY (inventory_transactions,
    inventory_balances, products, warehouses) where even the table owner must satisfy
    the RLS policy. The `true` flag makes the setting transaction-local.
    """
    conn.execute(
        text(
            "SELECT set_config('app.current_tenant_id', :tid, true),"
            "       set_config('app.current_user_id',   :tid, true)"
        ),
        {"tid": tid},
    )


def resolve_tenant_ids(conn, names_or_ids: list[str]) -> list[tuple[str, str]]:
    """Return list of (id, name) for the given names or UUIDs."""
    resolved = []
    for val in names_or_ids:
        try:
            uuid.UUID(val)
            row = conn.execute(
                text("SELECT id::text, name FROM tenants WHERE id = :v"),
                {"v": val},
            ).fetchone()
        except ValueError:
            row = conn.execute(
                text("SELECT id::text, name FROM tenants WHERE LOWER(name) = LOWER(:v)"),
                {"v": val},
            ).fetchone()

        if row is None:
            print(f"  [WARN] Tenant not found: '{val}' — skipping.", file=sys.stderr)
            continue

        tid, tname = row[0], row[1]

        # Safety guard
        if tname.lower() in PROTECTED_TENANT_NAMES or val.lower() in PROTECTED_TENANT_NAMES:
            print(f"  [PROTECTED] '{tname}' is in the protected list — skipping.", file=sys.stderr)
            continue

        resolved.append((tid, tname))
    return resolved


def _count_rows(conn, table: str, where: str, tid: str) -> int:
    if where == "__subquery__":
        return conn.execute(text(_ITK_COUNT), {"tid": tid}).scalar() or 0
    sql = f"SELECT COUNT(*) FROM {table} WHERE {where}"
    return conn.execute(text(sql), {"tid": tid}).scalar() or 0


def dry_run_report(conn, tenants: list[tuple[str, str]]) -> None:
    print("\n=== DRY RUN — no changes will be made ===\n")
    for tid, tname in tenants:
        # Set RLS context so policies allow the SELECTs
        conn.execute(
            text("SELECT set_config('app.current_tenant_id', :tid, true)"),
            {"tid": tid},
        )
        print(f"Tenant: {tname}  ({tid})")
        total = 0
        for table, where in TENANT_TABLES:
            n = _count_rows(conn, table, where, tid)
            if n:
                print(f"  {table:45s}  {n:>6} row(s) to delete")
                total += n
        print(f"  {'TOTAL':45s}  {total:>6} row(s)\n")


def purge_tenants(conn, tenants: list[tuple[str, str]]) -> None:
    """Delete all tenant data inside a single atomic transaction."""
    with conn.begin():
        # Drop the DELETE-blocking rules for append-only tables
        for rule, table in APPEND_ONLY_DELETE_RULES:
            conn.execute(text(f"DROP RULE IF EXISTS {rule} ON {table}"))
            print(f"  [RULE] Dropped {rule} on {table}")

        for tid, tname in tenants:
            print(f"\nDeleting: {tname}  ({tid})")

            # Set tenant context FIRST — satisfies RLS policies on FORCE RLS tables
            # (inventory_transactions, inventory_balances, products, warehouses).
            # All per-tenant deletes below require this to be set beforehand.
            _set_tenant_context(conn, tid)

            for table, where in TENANT_TABLES:
                if where == "__subquery__":
                    sql = _ITK_DELETE
                else:
                    sql = f"DELETE FROM {table} WHERE {where}"
                result = conn.execute(text(sql), {"tid": tid})
                if result.rowcount:
                    print(f"  {table:45s}  deleted {result.rowcount:>6} row(s)")

        # Recreate append-only rules before the transaction commits
        print("\nRecreating append-only rules...")
        for rule, table in APPEND_ONLY_DELETE_RULES:
            conn.execute(
                text(
                    f"CREATE RULE {rule} AS ON DELETE TO {table} DO INSTEAD NOTHING"
                )
            )
            print(f"  [RULE] Recreated {rule} on {table}")

    print("\nDone. Transaction committed.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Purge all data for one or more SMART tenants.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "tenants",
        nargs="+",
        metavar="NAME_OR_UUID",
        help="Tenant name(s) or UUID(s). Multiple allowed.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show row counts that would be deleted; make no changes.",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip the interactive confirmation prompt (for scripted use).",
    )
    args = parser.parse_args()

    # Step 1 — resolve tenant names/IDs (tenants table has no RLS — plain read)
    with engine.connect() as conn:
        tenants = resolve_tenant_ids(conn, args.tenants)
        conn.rollback()

    if not tenants:
        print("No tenants to process.")
        return

    print(f"\nTargeting {len(tenants)} tenant(s):")
    for tid, tname in tenants:
        print(f"  {tname}  ({tid})")

    if args.dry_run:
        with engine.connect() as conn:
            dry_run_report(conn, tenants)
            conn.rollback()
        return

    if not args.yes:
        print()
        confirm = input("Type YES to permanently delete all data for the above tenant(s): ").strip()
        if confirm != "YES":
            print("Aborted — no changes made.")
            return

    # Step 2 — purge (fresh connection, explicit transaction)
    with engine.connect() as conn:
        purge_tenants(conn, tenants)


if __name__ == "__main__":
    main()
