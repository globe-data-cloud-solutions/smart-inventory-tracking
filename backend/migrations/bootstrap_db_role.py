"""Create or update the runtime database role the app and migrations use.

Run once per deploy by the db-bootstrap ECS task, before `alembic upgrade head`.
It connects as the RDS master user (PGUSER/PGPASSWORD, injected by ECS from the
RDS-managed secret) and makes RUNTIME_DB_ROLE a non-superuser login role that
owns the objects its migrations create. Safe to run repeatedly.

Environment:
  PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD  master connection
  RUNTIME_DB_ROLE      role to create/update, e.g. smart_runtime
  RUNTIME_DB_PASSWORD  its password (alphanumeric, from the app-password secret)
"""

import asyncio
import os
import re
import sys

import asyncpg

ROLE_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
PASSWORD_PATTERN = re.compile(r"^[A-Za-z0-9]{32,}$")


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        sys.exit(f"bootstrap_db_role: missing required env var {name}")
    return value


async def bootstrap(conn: asyncpg.Connection, role: str, password: str) -> None:
    # The role name is validated against ROLE_PATTERN and the password against
    # PASSWORD_PATTERN, so interpolating them into DDL cannot inject SQL.
    exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", role)
    verb = "ALTER" if exists else "CREATE"
    await conn.execute(
        f'{verb} ROLE "{role}" WITH LOGIN PASSWORD \'{password}\' '
        "NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION"
    )
    database = await conn.fetchval("SELECT current_database()")
    # CREATE on the database lets the role install trusted extensions (pg_trgm
    # in migration 001). Without it the migration fails with "permission denied
    # to create extension".
    await conn.execute(f'GRANT CONNECT, CREATE ON DATABASE "{database}" TO "{role}"')
    # PostgreSQL 15+ no longer grants CREATE on public to everyone; the runtime
    # role needs it to run migrations that create tables.
    await conn.execute(f'GRANT USAGE, CREATE ON SCHEMA public TO "{role}"')


async def main() -> None:
    role = _required("RUNTIME_DB_ROLE")
    password = _required("RUNTIME_DB_PASSWORD")
    if not ROLE_PATTERN.match(role):
        sys.exit(f"bootstrap_db_role: invalid role name {role!r}")
    if not PASSWORD_PATTERN.match(password):
        sys.exit("bootstrap_db_role: RUNTIME_DB_PASSWORD must be alphanumeric, 32+ chars")

    conn = await asyncpg.connect(
        host=_required("PGHOST"),
        port=int(os.environ.get("PGPORT", "5432")),
        user=_required("PGUSER"),
        password=_required("PGPASSWORD"),
        database=_required("PGDATABASE"),
        ssl="require",
    )
    try:
        async with conn.transaction():
            await bootstrap(conn, role, password)
    finally:
        await conn.close()
    print(f"bootstrap_db_role: role {role!r} is ready")


if __name__ == "__main__":
    asyncio.run(main())
