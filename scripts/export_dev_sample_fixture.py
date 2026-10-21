"""Export the master/config rows of the dev sample tenants to a JSON fixture.

Reads the local development database (DATABASE_URL in the root .env) in a
read-only transaction and writes backend/migrations/seed/dev_sample_tenants.json,
which backend/migrations/seed_dev_sample.py replays in dev.

What is exported: the tenants, their hierarchy and org nodes, positions, users,
product configuration, approval/self-approval policy and transfer type config,
plus the SA account (tenant_id IS NULL).

What is NOT exported, on purpose:
  - transactional history (transfer orders, stock, payments, adjustments,
    outbox, audit and activity logs, renewal requests),
  - password hashes and login tokens (the seed generates passwords from
    Terraform-managed secrets),
  - product-specific rows (product_approval_minimums): the fixture has no
    products, so their product_id foreign keys could not be satisfied,
  - tenants other than the ones listed in TENANT_NAMES.

Run:  python scripts/export_dev_sample_fixture.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

TENANT_NAMES = ["T01", "TenantS10"]
SA_EMAIL = "smartadmin@smart-inventory.com"

# Insertion order: parents before children. Self-referencing rows are sorted
# below (parent-first) so that a single pass succeeds.
TABLES = [
    "tenants",
    "subscriptions",
    "tenant_contacts",
    "tenant_hierarchy_config",
    "organization_node",
    "org_node_hierarchy",
    "users",
    "positions",
    "personnel_positions",
    "product_categories",
    "product_type_codes",
    "product_uoms",
    "product_packaging_types",
    "self_approval_policies",
    "transfer_type_config",
    "transfer_type_level_permissions",
]

OUT = (
    Path(__file__).resolve().parent.parent
    / "backend"
    / "migrations"
    / "seed"
    / "dev_sample_tenants.json"
)


def _database_url() -> str:
    env_file = Path(__file__).resolve().parent.parent / ".env"
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("DATABASE_URL="):
            url = line.split("=", 1)[1].strip().strip('"').strip("'")
            # psql wants a libpq URL, not the SQLAlchemy driver form.
            return url.replace("postgresql+asyncpg://", "postgresql://", 1)
    sys.exit("DATABASE_URL not found in .env")


def _query(url: str, sql: str) -> str:
    # Read-only transaction: the export cannot write to the dev database.
    wrapped = f"BEGIN READ ONLY; {sql}; ROLLBACK;"
    result = subprocess.run(
        ["psql", url, "-X", "-At", "-v", "ON_ERROR_STOP=1", "-c", wrapped],
        capture_output=True,
        text=True,
        check=True,
    )
    # json_agg output spans several lines (one per row); keep everything between
    # the transaction markers.
    body = [
        ln
        for ln in result.stdout.splitlines()
        if ln.strip() not in ("BEGIN", "ROLLBACK")
    ]
    return "\n".join(body) if body else "[]"


def _scope(table: str) -> str:
    names = ", ".join(f"'{n}'" for n in TENANT_NAMES)
    tenant_ids = f"(SELECT id FROM tenants WHERE name IN ({names}))"
    if table == "tenants":
        return f"name IN ({names})"
    if table == "users":
        return (
            f"tenant_id IN {tenant_ids} OR (tenant_id IS NULL AND email = '{SA_EMAIL}')"
        )
    return f"tenant_id IN {tenant_ids}"


def _sort_parent_first(table: str, rows: list[dict]) -> list[dict]:
    parent_col = {
        "organization_node": "parent_node_id",
        "positions": "reports_to_position_id",
        "product_categories": "parent_id",
    }.get(table)
    if not parent_col:
        return rows
    by_id = {r["id"]: r for r in rows}
    ordered: list[dict] = []
    placed: set[str] = set()

    def place(row: dict) -> None:
        if row["id"] in placed:
            return
        parent = row.get(parent_col)
        if parent in by_id:
            place(by_id[parent])
        placed.add(row["id"])
        ordered.append(row)

    for r in rows:
        place(r)
    return ordered


def main() -> None:
    url = _database_url()
    fixture: dict[str, list[dict]] = {}
    for table in TABLES:
        raw = _query(
            url,
            f"SELECT coalesce(json_agg(t), '[]'::json) FROM (SELECT * FROM {table} WHERE {_scope(table)}) t",
        )
        rows = json.loads(raw)
        for r in rows:
            # Never export credentials; the seed sets these from Terraform secrets.
            r.pop("password_hash", None)
            r.pop("cognito_sub", None)
        fixture[table] = _sort_parent_first(table, rows)
        print(f"{table}: {len(rows)} rows")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(fixture, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT}")


if __name__ == "__main__":
    os.chdir(Path(__file__).resolve().parent.parent)
    main()
