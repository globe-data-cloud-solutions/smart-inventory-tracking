"""
delete_tenant.py — Reusable tenant purge script.

Deletes ALL data for one or more tenants from the database, handling:
  - PostgreSQL RLS — the connecting role (smart_user) is the table owner, so it
    bypasses RLS on tables without FORCE ROW LEVEL SECURITY. For FORCE RLS tables
    (inventory_transactions, inventory_balances, products, warehouses) the owner
    must still satisfy the policy, so app.current_tenant_id is set per tenant
    before every delete/check that touches them.
  - Append-only RULE tables — DELETE-blocking no_delete_* rules on every table in
    the purge set are discovered from pg_rules, dropped at the start of the purge
    transaction, and recreated before commit.
  - FK ordering — discovered from pg_constraint and topologically sorted
    (children before parents) instead of a hand-maintained list.
  - Tables without tenant_id that reference a purged table by FK (e.g.
    email_verification_tokens, password_reset_tokens) are discovered automatically
    and deleted via a subquery on the referenced column.
  - inventory_transaction_keys has no tenant_id AND no declared FK constraint
    (the transaction_id relationship is enforced only in application code) — kept
    as a hard-coded special case since FK discovery cannot find it.

Usage:
    # Single/multi tenant, by name or UUID (existing behaviour, unchanged):
    python scripts/delete_tenant.py --dry-run "Tenant 01" "T2" "T03"
    python scripts/delete_tenant.py "Tenant 01" "T2" "T03"
    python scripts/delete_tenant.py --id a1b2c3d4-0000-0000-0000-000000000001

    # Purge every tenant EXCEPT the named ones (and any tenant holding a
    # system_role=SA user, kept unconditionally):
    python scripts/delete_tenant.py --dry-run --all-except "T01" "T08" "Tenant_6_P2T" "zz-e2e-ta"
    python scripts/delete_tenant.py --all-except "T01" "T08" "Tenant_6_P2T" "zz-e2e-ta"

Requires: DATABASE_URL env var. The connecting user must have DELETE privileges on
all tables and be the table owner (or have BYPASSRLS) to skip RLS.

SAFE: Tenant 6 (Tenant_6_P2T) and Tenant 07 are excluded even if accidentally passed
in single/multi-tenant mode (PROTECTED_TENANT_NAMES). --all-except mode is keep-list
driven instead — see resolve_keep_list().

LOCAL DEV ONLY per CLAUDE.md §8 — never run against staging or prod.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from collections import defaultdict, deque

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from sqlalchemy import create_engine, text

# ---------------------------------------------------------------------------
# Connection — sync driver
# ---------------------------------------------------------------------------
_raw_url = os.environ["DATABASE_URL"]
_sync_url = _raw_url.replace("postgresql+asyncpg://", "postgresql://").replace(
    "postgresql+psycopg2://", "postgresql://"
)
engine = create_engine(_sync_url, echo=False)

# ---------------------------------------------------------------------------
# Safety guard — single/multi-tenant mode never deletes these regardless of input
# ---------------------------------------------------------------------------
PROTECTED_TENANT_NAMES = {
    "tenant_6_p2t",
    "tenant 6",
    "t6",
    "tenant_07",
    "tenant 07",
    "t7",
}

# Hard-coded special case: no tenant_id column AND no declared FK constraint,
# so FK discovery below cannot find it. transaction_id -> inventory_transactions.id.
_ITK_TABLE = "inventory_transaction_keys"
_ITK_DELETE = (
    "DELETE FROM inventory_transaction_keys "
    "WHERE transaction_id IN "
    "(SELECT id FROM inventory_transactions WHERE tenant_id = :tid)"
)
_ITK_ORPHAN_COUNT = (
    "SELECT COUNT(*) FROM inventory_transaction_keys k "
    "WHERE NOT EXISTS (SELECT 1 FROM inventory_transactions t WHERE t.id = k.transaction_id)"
)


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------


def discover_tenant_tables(conn) -> list[str]:
    """Every public base table with a tenant_id column, excluding `tenants`
    itself and excluding partition children (deleted via their parent)."""
    rows = conn.execute(
        text(
            """
            SELECT c.table_name
            FROM information_schema.columns c
            JOIN information_schema.tables t
              ON t.table_name = c.table_name AND t.table_schema = 'public'
            WHERE c.table_schema = 'public'
              AND c.column_name = 'tenant_id'
              AND t.table_type = 'BASE TABLE'
            ORDER BY c.table_name
            """
        )
    ).fetchall()
    candidates = [r[0] for r in rows if r[0] != "tenants"]

    partition_children = {
        r[0]
        for r in conn.execute(
            text(
                """
                SELECT i.inhrelid::regclass::text
                FROM pg_inherits i
                JOIN pg_class c ON c.oid = i.inhrelid AND c.relkind = 'r'
                """
            )
        ).fetchall()
    }
    return [t for t in candidates if t not in partition_children]


def get_all_fks(conn) -> list[dict]:
    """Single-column FK edges in the public schema: child table/column ->
    parent table/column."""
    rows = conn.execute(
        text(
            """
            SELECT
                con.conrelid::regclass::text  AS child_table,
                ac.attname                    AS child_col,
                con.confrelid::regclass::text AS parent_table,
                ap.attname                    AS parent_col
            FROM pg_constraint con
            JOIN pg_attribute ac ON ac.attrelid = con.conrelid AND ac.attnum = con.conkey[1]
            JOIN pg_attribute ap ON ap.attrelid = con.confrelid AND ap.attnum = con.confkey[1]
            WHERE con.contype = 'f'
              AND con.connamespace = 'public'::regnamespace
              AND array_length(con.conkey, 1) = 1
            """
        )
    ).fetchall()
    return [
        {
            "child_table": r[0],
            "child_col": r[1],
            "parent_table": r[2],
            "parent_col": r[3],
        }
        for r in rows
    ]


def discover_fk_only_tables(
    conn, tenant_tables: list[str], all_fks: list[dict]
) -> list[dict]:
    """Tables without tenant_id whose FK points at a table in the purge set
    (tenant_tables, or 'users'/'tenants'/'organization_node'). Excludes the
    hard-coded inventory_transaction_keys special case (no real FK exists for it)."""
    purge_targets = set(tenant_tables) | {"users", "tenants", "organization_node"}
    found = {}
    for fk in all_fks:
        child, parent = fk["child_table"], fk["parent_table"]
        if child in tenant_tables or child == "tenants" or child == _ITK_TABLE:
            continue
        if parent not in purge_targets:
            continue
        # Confirm the child genuinely lacks tenant_id (else it's a direct table already)
        has_tenant_id = conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=:t AND column_name='tenant_id'"
            ),
            {"t": child},
        ).fetchone()
        if has_tenant_id:
            continue
        found[child] = fk
    return list(found.values())


def topo_order(nodes: set[str], edges: list[tuple[str, str]]) -> list[str]:
    """Kahn's algorithm. edges = (child, parent) meaning child must precede
    parent in the returned order. Self-loops are ignored."""
    deps: dict[str, set[str]] = defaultdict(set)  # node -> nodes it must come after
    children_of: dict[str, set[str]] = defaultdict(
        set
    )  # parent -> children waiting on it
    for child, parent in edges:
        if child == parent or child not in nodes or parent not in nodes:
            continue
        if parent not in deps[child]:
            deps[child].add(parent)
            children_of[parent].add(child)

    # Kahn's algorithm on the reversed graph: a parent can be deleted only
    # once all of its children have been deleted first.
    remaining_children = {n: set(children_of[n]) for n in nodes}
    ready = deque(sorted(n for n in nodes if not remaining_children[n]))
    order = []
    seen = set()
    while ready:
        n = ready.popleft()
        if n in seen:
            continue
        seen.add(n)
        order.append(n)
        for parent in deps.get(n, ()):
            remaining_children[parent].discard(n)
            if not remaining_children[parent] and parent not in seen:
                ready.append(parent)
    leftover = nodes - seen
    if leftover:
        # Cycle among non-self edges — shouldn't happen; append deterministically.
        order.extend(sorted(leftover))
    return order


def discover_append_only_rules(conn, purge_tables: list[str]) -> list[tuple[str, str]]:
    """DELETE-blocking rules (no_delete_*) on tables we're about to purge."""
    rows = conn.execute(
        text(
            """
            SELECT rulename, tablename FROM pg_rules
            WHERE schemaname = 'public' AND rulename LIKE 'no_delete_%'
            """
        )
    ).fetchall()
    return [(r[0], r[1]) for r in rows if r[1] in purge_tables]


def build_purge_plan(conn) -> dict:
    """Compute, once per run, the full table set, deletion order, FK-only
    special-case tables, and append-only rules affected by a purge."""
    tenant_tables = discover_tenant_tables(conn)
    all_fks = get_all_fks(conn)
    fk_only = discover_fk_only_tables(conn, tenant_tables, all_fks)
    fk_only_names = [f["child_table"] for f in fk_only]

    node_set = set(tenant_tables) | set(fk_only_names) | {_ITK_TABLE, "tenants"}

    edges = [
        (fk["child_table"], fk["parent_table"])
        for fk in all_fks
        if fk["child_table"] in node_set and fk["parent_table"] in node_set
    ]
    # Special-case tables precede their FK parent.
    for fk in fk_only:
        edges.append((fk["child_table"], fk["parent_table"]))
    edges.append((_ITK_TABLE, "inventory_transactions"))

    order = topo_order(node_set, edges)
    # tenants must be strictly last regardless of the graph.
    order = [t for t in order if t != "tenants"] + ["tenants"]

    rules = discover_append_only_rules(conn, [t for t in order if t != "tenants"])

    return {
        "order": order,
        "fk_only": {f["child_table"]: f for f in fk_only},
        "rules": rules,
    }


# ---------------------------------------------------------------------------
# Tenant resolution
# ---------------------------------------------------------------------------


def resolve_tenant_ids(conn, names_or_ids: list[str]) -> list[tuple[str, str]]:
    """Return list of (id, name) for the given names or UUIDs. (Single/multi mode.)"""
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
                text(
                    "SELECT id::text, name FROM tenants WHERE LOWER(name) = LOWER(:v)"
                ),
                {"v": val},
            ).fetchone()

        if row is None:
            print(f"  [WARN] Tenant not found: '{val}' — skipping.", file=sys.stderr)
            continue

        tid, tname = row[0], row[1]

        if (
            tname.lower() in PROTECTED_TENANT_NAMES
            or val.lower() in PROTECTED_TENANT_NAMES
        ):
            print(
                f"  [PROTECTED] '{tname}' is in the protected list — skipping.",
                file=sys.stderr,
            )
            continue

        resolved.append((tid, tname))
    return resolved


def resolve_keep_list(conn, keep_names: list[str]) -> list[tuple[str, str, str]]:
    """Resolve each keep-list entry (slug or name, case-insensitive) to EXACTLY
    one tenant. Aborts (raises SystemExit) printing candidates on 0 or >1 matches.
    Returns list of (id, slug, name)."""
    resolved: list[tuple[str, str, str]] = []
    for val in keep_names:
        rows = conn.execute(
            text(
                "SELECT id::text, slug, name FROM tenants "
                "WHERE LOWER(slug) = LOWER(:v) OR LOWER(name) = LOWER(:v)"
            ),
            {"v": val},
        ).fetchall()
        if len(rows) != 1:
            print(
                f"\n[ABORT] Keep-list entry '{val}' matched {len(rows)} tenant(s):",
                file=sys.stderr,
            )
            for r in rows:
                print(f"    {r[0]}  slug={r[1]}  name={r[2]}", file=sys.stderr)
            if not rows:
                print("    (no candidates)", file=sys.stderr)
            raise SystemExit(1)
        tid, slug, name = rows[0]
        print(f"  Keep '{val}' -> {tid}  slug={slug}  name={name}")
        resolved.append((tid, slug, name))
    return resolved


def get_sa_holding_tenant_ids(conn) -> set[str]:
    rows = conn.execute(
        text("SELECT DISTINCT tenant_id::text FROM users WHERE system_role = 'SA'")
    ).fetchall()
    return {r[0] for r in rows}


# ---------------------------------------------------------------------------
# Core delete / count helpers
# ---------------------------------------------------------------------------


def _set_tenant_context(conn, tid: str) -> None:
    """Set app.current_tenant_id so RLS policies evaluate TRUE for this tenant's
    rows. Required for FORCE RLS tables (inventory_transactions, inventory_balances,
    products, warehouses) where even the table owner must satisfy the policy."""
    conn.execute(
        text(
            "SELECT set_config('app.current_tenant_id', :tid, true),"
            "       set_config('app.current_user_id',   :tid, true)"
        ),
        {"tid": tid},
    )


def _delete_table(conn, table: str, plan: dict, tid: str) -> int:
    if table == _ITK_TABLE:
        return conn.execute(text(_ITK_DELETE), {"tid": tid}).rowcount
    if table in plan["fk_only"]:
        fk = plan["fk_only"][table]
        sql = (
            f"DELETE FROM {table} "
            f"WHERE {fk['child_col']} IN (SELECT {fk['parent_col']} FROM {fk['parent_table']} WHERE tenant_id = :tid)"
        )
        return conn.execute(text(sql), {"tid": tid}).rowcount
    where = "id = :tid" if table == "tenants" else "tenant_id = :tid"
    return conn.execute(
        text(f"DELETE FROM {table} WHERE {where}"), {"tid": tid}
    ).rowcount


def run_purge_transaction(
    targets: list[tuple[str, str]],
    plan: dict,
    kept_tenants: list[tuple[str, str]],
    tenants_before: int,
    dry_run: bool,
) -> bool:
    """Open one connection/transaction, run execute_purge, then ROLLBACK
    (dry-run or failed orphan check) or COMMIT (live + clean). Returns True
    if the purge was committed."""
    with engine.connect() as conn:
        txn = conn.begin()
        label = "DRY RUN" if dry_run else "LIVE PURGE"
        print(
            f"\n=== {label} — deletes run in a transaction, "
            f"{'ROLLBACK' if dry_run else 'COMMIT'} at the end ==="
        )
        orphans = execute_purge(conn, targets, plan, kept_tenants)

        if dry_run or orphans:
            txn.rollback()
            if orphans:
                print("\n[ABORT] Orphan check failed — rolled back, no changes made.")
            else:
                print("\nDRY RUN complete — rolled back, no changes made.")
            committed = False
        else:
            txn.commit()
            print("\nDone. Transaction committed.")
            committed = True

    with engine.connect() as conn:
        after = conn.execute(text("SELECT COUNT(*) FROM tenants")).scalar()
        conn.rollback()
    print(f"Tenant count before: {tenants_before}  after: {after}")
    return committed


def execute_purge(
    conn,
    targets: list[tuple[str, str]],
    plan: dict,
    kept_tenants: list[tuple[str, str]],
) -> int:
    """Drop append-only rules, delete every table for every target tenant,
    recreate the rules, then run the orphan check — all against the connection's
    CURRENT transaction (caller controls commit/rollback). Prints per-tenant and
    per-table counts. Returns the orphan count (0 = clean)."""
    for rule, table in plan["rules"]:
        conn.execute(text(f"DROP RULE IF EXISTS {rule} ON {table}"))
        print(f"  [RULE] Dropped {rule} on {table}")

    totals: dict[str, int] = defaultdict(int)
    grand_total = 0
    for tid, tname in targets:
        print(f"\nDeleting: {tname}  ({tid})")
        _set_tenant_context(conn, tid)
        tenant_total = 0
        for table in plan["order"]:
            n = _delete_table(conn, table, plan, tid)
            if n:
                print(f"  {table:45s}  deleted {n:>6} row(s)")
                totals[table] += n
                tenant_total += n
        print(f"  {'TOTAL':45s}  {tenant_total:>6} row(s)")
        grand_total += tenant_total

    print(
        f"\n=== Per-table totals across {len(targets)} tenant(s) (grand total {grand_total}) ==="
    )
    for table in plan["order"]:
        if totals[table]:
            print(f"  {table:45s}  {totals[table]:>6}")

    print("\nRecreating append-only rules...")
    for rule, table in plan["rules"]:
        conn.execute(
            text(f"CREATE RULE {rule} AS ON DELETE TO {table} DO INSTEAD NOTHING")
        )
        print(f"  [RULE] Recreated {rule} on {table}")

    print("\nOrphan check...")
    orphans = orphan_check(conn, plan, kept_tenants)
    print(f"  Total orphans: {orphans}")
    return orphans


def orphan_check(conn, plan: dict, kept_tenants: list[tuple[str, str]]) -> int:
    """Post-delete integrity check. Returns total orphan count found (0 = clean)."""
    total_orphans = 0

    # FK-only / no-tenant_id special tables: DB-wide, no RLS on them.
    for table, fk in plan["fk_only"].items():
        sql = (
            f"SELECT COUNT(*) FROM {table} c WHERE c.{fk['child_col']} IS NOT NULL "
            f"AND NOT EXISTS (SELECT 1 FROM {fk['parent_table']} p WHERE p.{fk['parent_col']} = c.{fk['child_col']})"
        )
        n = conn.execute(text(sql)).scalar() or 0
        if n:
            print(
                f"  [ORPHAN] {table}.{fk['child_col']} -> {fk['parent_table']}: {n} row(s)"
            )
        total_orphans += n

    # inventory_transaction_keys has no declared FK constraint (soft/app-enforced
    # reference only) — informational only, does not fail the orphan check or
    # block commit. Pre-existing drift here is a known idempotency-key cleanup
    # gap, unrelated to this purge.
    n = conn.execute(text(_ITK_ORPHAN_COUNT)).scalar() or 0
    if n:
        print(
            f"  [INFO] {_ITK_TABLE}.transaction_id -> inventory_transactions: "
            f"{n} row(s) with no matching transaction (pre-existing, no real FK; not counted as a failure)"
        )

    # Direct tenant-scoped tables: per kept tenant, with RLS context set
    # (covers FORCE RLS tables: inventory_transactions, inventory_balances,
    # products, warehouses).
    direct_tables = set(plan["order"]) - set(plan["fk_only"]) - {_ITK_TABLE}
    direct_edges = [
        (fk["child_table"], fk["child_col"], fk["parent_table"], fk["parent_col"])
        for fk in get_all_fks(conn)
        if fk["child_table"] in direct_tables
        and fk["parent_table"] in direct_tables
        and fk["child_table"] != fk["parent_table"]
        and fk["child_table"] != "tenants"
        and fk["parent_table"] != "tenants"
    ]
    for tid, tname in kept_tenants:
        _set_tenant_context(conn, tid)
        for child, child_col, parent, parent_col in direct_edges:
            sql = (
                f"SELECT COUNT(*) FROM {child} c WHERE c.tenant_id = :tid "
                f"AND c.{child_col} IS NOT NULL "
                f"AND NOT EXISTS (SELECT 1 FROM {parent} p WHERE p.{parent_col} = c.{child_col})"
            )
            n = conn.execute(text(sql), {"tid": tid}).scalar() or 0
            if n:
                print(
                    f"  [ORPHAN] tenant {tname}: {child}.{child_col} -> {parent}: {n} row(s)"
                )
            total_orphans += n

    return total_orphans


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Purge all data for one or more SMART tenants. LOCAL DEV ONLY.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "tenants",
        nargs="*",
        metavar="NAME_OR_UUID",
        help="Tenant name(s) or UUID(s). Multiple allowed. Mutually exclusive with --all-except.",
    )
    parser.add_argument(
        "--all-except",
        nargs="+",
        metavar="NAME_OR_SLUG",
        help="Purge every tenant EXCEPT the named ones (match by slug or name, "
        "case-insensitive, exactly one each) and any tenant holding a "
        "system_role=SA user.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show row counts that would be deleted; make no changes.",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip the interactive confirmation prompt (for scripted use).",
    )
    args = parser.parse_args()

    if args.tenants and args.all_except:
        parser.error(
            "--all-except cannot be combined with explicit tenant names/UUIDs."
        )
    if not args.tenants and not args.all_except:
        parser.error("Provide tenant name(s)/UUID(s), or use --all-except.")

    with engine.connect() as conn:
        plan = build_purge_plan(conn)
        conn.rollback()
    print(
        f"Purge plan: {len(plan['order'])} tables, deletion order resolved via pg_constraint."
    )
    print(
        f"FK-only special-case tables discovered: {sorted(plan['fk_only'].keys()) or '(none)'}"
    )
    print(f"Append-only rules affected: {plan['rules'] or '(none)'}")

    if args.all_except:
        with engine.connect() as conn:
            print("\nResolving keep-list:")
            keep = resolve_keep_list(conn, args.all_except)
            keep_ids = {k[0] for k in keep}

            sa_ids = get_sa_holding_tenant_ids(conn)
            if sa_ids:
                print(
                    f"\nAlso keeping {len(sa_ids)} tenant(s) holding a system_role=SA user:"
                )
                for r in conn.execute(
                    text(
                        "SELECT id::text, slug, name FROM tenants WHERE id::text = ANY(:ids)"
                    ),
                    {"ids": list(sa_ids)},
                ):
                    print(f"    {r[0]}  slug={r[1]}  name={r[2]}")
            keep_ids |= sa_ids

            all_rows = conn.execute(
                text(
                    "SELECT id::text, slug, name, created_at FROM tenants ORDER BY created_at"
                )
            ).fetchall()
            conn.rollback()

        tenants_before = len(all_rows)
        purge_targets = [(r[0], r[2]) for r in all_rows if r[0] not in keep_ids]
        kept_tenants = [(r[0], r[2]) for r in all_rows if r[0] in keep_ids]

        print(
            f"\nPURGE target: {len(purge_targets)} tenant(s) (of {tenants_before} total):"
        )
        for r in all_rows:
            if r[0] not in keep_ids:
                print(f"  {r[0]}  slug={r[1]}  name={r[2]}  created_at={r[3]}")

        if not purge_targets:
            print("\nNothing to purge.")
            return

        if not args.dry_run and not args.yes:
            print()
            confirm = input(
                f"Type YES to permanently delete all data for {len(purge_targets)} tenant(s): "
            ).strip()
            if confirm != "YES":
                print("Aborted — no changes made.")
                return

        run_purge_transaction(
            purge_targets, plan, kept_tenants, tenants_before, args.dry_run
        )
        return

    # ---- Single/multi-tenant mode (unchanged behaviour) ----
    with engine.connect() as conn:
        tenants = resolve_tenant_ids(conn, args.tenants)
        tenants_before = conn.execute(text("SELECT COUNT(*) FROM tenants")).scalar()
        all_other = conn.execute(text("SELECT id::text, name FROM tenants")).fetchall()
        conn.rollback()

    if not tenants:
        print("No tenants to process.")
        return

    print(f"\nTargeting {len(tenants)} tenant(s):")
    for tid, tname in tenants:
        print(f"  {tname}  ({tid})")

    purge_ids = {t[0] for t in tenants}
    kept_tenants = [(r[0], r[1]) for r in all_other if r[0] not in purge_ids]

    if not args.dry_run and not args.yes:
        print()
        confirm = input(
            "Type YES to permanently delete all data for the above tenant(s): "
        ).strip()
        if confirm != "YES":
            print("Aborted — no changes made.")
            return

    run_purge_transaction(tenants, plan, kept_tenants, tenants_before, args.dry_run)


if __name__ == "__main__":
    main()
