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
  DATABASE_URL          runtime role (smart_runtime), SQLAlchemy or libpq form
  SEED_SA_PASSWORD, SEED_SAMPLE_PASSWORD
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

import asyncpg
import bcrypt

FIXTURE = Path(__file__).resolve().parent / "seed" / "dev_sample_tenants.json"
SA_EMAIL = "smartadmin@smart-inventory.com"


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        sys.exit(f"seed_dev_sample: missing required env var {name}")
    return value


def _connect_kwargs(url: str) -> dict:
    # The app's URL carries the SQLAlchemy driver and a ?ssl= query. asyncpg
    # rejects ?ssl= inside a DSN ("parameter ssl cannot be changed now"), so
    # split the URL and pass ssl as a keyword, as bootstrap_db_role.py does.
    parts = urlsplit(url.replace("postgresql+asyncpg://", "postgresql://", 1))
    return {
        "host": parts.hostname,
        "port": parts.port or 5432,
        "user": unquote(parts.username or ""),
        "password": unquote(parts.password or ""),
        "database": parts.path.lstrip("/"),
        "ssl": "require",
    }


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _row_tenant(table: str, row: dict) -> str | None:
    return row["id"] if table == "tenants" else row.get("tenant_id")


async def _insert(conn: asyncpg.Connection, table: str, row: dict) -> None:
    # json_populate_record coerces each JSON value to the column's own type
    # (uuid, timestamptz, enum, arrays, jsonb), so the fixture stays plain JSON.
    # The table name comes from the fixture and is double-quoted.
    await conn.execute(
        f'INSERT INTO "{table}" SELECT (json_populate_record(NULL::"{table}", $1::json)).* '
        "ON CONFLICT DO NOTHING",
        json.dumps(row),
    )


async def main() -> None:
    if os.environ.get("SEED_ENABLED") != "true":
        print("seed_dev_sample: SEED_ENABLED is not 'true' — nothing to do.")
        return

    sa_password = _required("SEED_SA_PASSWORD")
    sample_password = _required("SEED_SAMPLE_PASSWORD")
    fixture: dict[str, list[dict]] = json.loads(FIXTURE.read_text(encoding="utf-8"))

    conn = await asyncpg.connect(**_connect_kwargs(_required("DATABASE_URL")))
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
                await _insert(conn, "users", {**sa_row, "password_hash": _hash(sa_password)})
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
                await _insert(conn, "tenants", tenant)
                # Fixture order keeps parents first: users come before the
                # tables that reference them (personnel_positions, policies).
                for table in fixture:
                    if table == "tenants":
                        continue
                    for row in fixture[table]:
                        if _row_tenant(table, row) != tid:
                            continue
                        if table == "users":
                            row = {**row, "password_hash": _hash(sample_password)}
                        await _insert(conn, table, row)
            print(f"seed_dev_sample: created tenant {name}.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
