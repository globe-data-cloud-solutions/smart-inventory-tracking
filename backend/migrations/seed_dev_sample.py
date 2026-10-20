"""Seed the dev sample tenants and the SA account. Dev only.

Run by the seed ECS task after migrations, on every dev deploy. It replays
backend/migrations/seed/dev_sample_tenants.json, which is exported from the
development database by scripts/export_dev_sample_fixture.py.

First creation only (except SA rotation, below):
  - each tenant is created only if its id does not exist yet, in its own
    transaction, so a re-deploy never touches an existing tenant;
  - the SA account is created only if its email does not exist yet.
Passwords are set at creation only; a re-deploy never changes them.

Passwords come from Terraform-managed secrets (never from the fixture):
  SEED_SA_PASSWORD      SA account (smartadmin@smart-inventory.com)
  SEED_SAMPLE_PASSWORD  every sample tenant user

Environment:
  SEED_ENABLED=true     required; anything else exits without writing
  SEED_ROTATE_SA=true   delete and re-create the SA account from the current
                        secret (rotation); off by default
  MIGRATION_DATABASE_URL  owner role (smart_owner), SQLAlchemy or libpq form;
                          falls back to DATABASE_URL (local dev)
  SEED_SA_PASSWORD, SEED_SAMPLE_PASSWORD
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import asyncpg

from migrations.seed_common import (
    FIXTURE,
    SA_EMAIL,
    connect_kwargs,
    hash_password,
    insert_row,
)


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        sys.exit(f"seed_dev_sample: missing required env var {name}")
    return value


def _row_tenant(table: str, row: dict) -> str | None:
    return row["id"] if table == "tenants" else row.get("tenant_id")


async def _resolve_price(conn: asyncpg.Connection, row: dict) -> dict:
    # package_prices ids differ between databases (the local one has accumulated
    # price history), so resolve the subscription's price in this database by
    # tier, billing period and currency. price_id is nullable: no match = NULL.
    price_id = await conn.fetchval(
        "SELECT id FROM package_prices WHERE tier = $1 AND billing_period = $2 AND currency = $3 "
        "ORDER BY effective_from DESC LIMIT 1",
        row["tier"], row["billing_period"], row["currency"],
    )
    return {**row, "price_id": str(price_id) if price_id else None}


async def main() -> None:
    if os.environ.get("SEED_ENABLED") != "true":
        print("seed_dev_sample: SEED_ENABLED is not 'true' — nothing to do.")
        return

    sa_password = _required("SEED_SA_PASSWORD")
    sample_password = _required("SEED_SAMPLE_PASSWORD")
    fixture: dict[str, list[dict]] = json.loads(FIXTURE.read_text(encoding="utf-8"))

    db_url = os.environ.get("MIGRATION_DATABASE_URL") or _required("DATABASE_URL")
    conn = await asyncpg.connect(**connect_kwargs(db_url))
    try:
        # SA account: tenant_id IS NULL, identified by email. Rotation (see
        # SEED_ROTATE_SA) deletes it and re-creates it from the current secret,
        # in one transaction, so there is never a window without the account.
        sa_row = next(r for r in fixture["users"] if r["email"] == SA_EMAIL)
        rotate = os.environ.get("SEED_ROTATE_SA") == "true"
        async with conn.transaction():
            if rotate:
                await conn.execute("DELETE FROM users WHERE email = $1", SA_EMAIL)
            if await conn.fetchval("SELECT 1 FROM users WHERE email = $1", SA_EMAIL):
                print(f"seed_dev_sample: {SA_EMAIL} exists — skipped.")
            else:
                await insert_row(conn, "users", {**sa_row, "password_hash": hash_password(sa_password)})
                print(f"seed_dev_sample: {'rotated and ' if rotate else ''}created {SA_EMAIL}.")

        for tenant in fixture["tenants"]:
            tid = tenant["id"]
            name = tenant["name"]
            if await conn.fetchval("SELECT 1 FROM tenants WHERE id = $1", tid):
                print(f"seed_dev_sample: tenant {name} exists — skipped.")
                continue

            async with conn.transaction():
                # Writes to tenant-scoped tables are checked against this setting.
                await conn.execute("SELECT set_config('app.current_tenant_id', $1, true)", tid)
                await insert_row(conn, "tenants", tenant)
                # Fixture order keeps parents first: users come before the
                # tables that reference them (personnel_positions, policies).
                for table in fixture:
                    if table == "tenants":
                        continue
                    for row in fixture[table]:
                        if _row_tenant(table, row) != tid:
                            continue
                        if table == "users":
                            row = {**row, "password_hash": hash_password(sample_password)}
                        if table == "subscriptions":
                            row = await _resolve_price(conn, row)
                        await insert_row(conn, table, row)
            print(f"seed_dev_sample: created tenant {name}.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
