"""Create or update the owner and runtime database roles.

Run once per deploy by the db-bootstrap ECS task, before `alembic upgrade head`.
It connects as the RDS master user (PGUSER/PGPASSWORD, injected by ECS from the
RDS-managed secret) and makes two non-superuser login roles:

  OWNER_DB_ROLE    runs migrations (MIGRATION_DATABASE_URL) and owns the
                   objects they create. Has CREATE on the database and schema.
  RUNTIME_DB_ROLE  the app and workers (DATABASE_URL). CONNECT and USAGE only;
                   table privileges come from migration 091's grants. It never
                   owns a table, so RLS applies to it.

Safe to run repeatedly.

Environment:
  PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD  master connection
  OWNER_DB_ROLE        owner role, default smart_owner
  OWNER_DB_PASSWORD    its password (alphanumeric, from the owner-password secret)
  RUNTIME_DB_ROLE      runtime role, e.g. smart_runtime
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


def _validated(
    role_var: str, password_var: str, default_role: str | None = None
) -> tuple[str, str]:
    role = os.environ.get(role_var, "") or default_role or _required(role_var)
    password = _required(password_var)
    if not ROLE_PATTERN.match(role):
        sys.exit(f"bootstrap_db_role: invalid role name {role!r}")
    if not PASSWORD_PATTERN.match(password):
        sys.exit(f"bootstrap_db_role: {password_var} must be alphanumeric, 32+ chars")
    return role, password


async def _ensure_role(conn: asyncpg.Connection, role: str, password: str) -> None:
    # The role name is validated against ROLE_PATTERN and the password against
    # PASSWORD_PATTERN, so interpolating them into DDL cannot inject SQL.
    # The master is not a superuser, so ALTER ROLE must not touch SUPERUSER or
    # BYPASSRLS (Postgres rejects it even when setting NOSUPERUSER). Roles are
    # created non-superuser without BYPASSRLS by default, so those attributes
    # are only set at CREATE time.
    exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", role)
    if exists:
        await conn.execute(f"ALTER ROLE \"{role}\" WITH LOGIN PASSWORD '{password}'")
    else:
        await conn.execute(
            f"CREATE ROLE \"{role}\" WITH LOGIN PASSWORD '{password}' "
            "NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS"
        )


async def bootstrap(
    conn: asyncpg.Connection,
    owner_role: str,
    owner_password: str,
    runtime_role: str,
    runtime_password: str,
) -> None:
    if owner_role == runtime_role:
        sys.exit("bootstrap_db_role: OWNER_DB_ROLE and RUNTIME_DB_ROLE must differ")
    await _ensure_role(conn, owner_role, owner_password)
    await _ensure_role(conn, runtime_role, runtime_password)
    database = await conn.fetchval("SELECT current_database()")

    # Owner: CREATE on the database lets it install trusted extensions (pg_trgm
    # in migration 001); without it the migration fails with "permission denied
    # to create extension". PostgreSQL 15+ no longer grants CREATE on public to
    # everyone, and the owner needs it to create tables.
    await conn.execute(
        f'GRANT CONNECT, CREATE ON DATABASE "{database}" TO "{owner_role}"'
    )
    await conn.execute(f'GRANT USAGE, CREATE ON SCHEMA public TO "{owner_role}"')

    # Runtime: connect and resolve names only. The REVOKEs remove CREATE from a
    # database bootstrapped before the owner/runtime split; they are no-ops
    # otherwise.
    await conn.execute(f'GRANT CONNECT ON DATABASE "{database}" TO "{runtime_role}"')
    await conn.execute(f'REVOKE CREATE ON DATABASE "{database}" FROM "{runtime_role}"')
    await conn.execute(f'GRANT USAGE ON SCHEMA public TO "{runtime_role}"')
    await conn.execute(f'REVOKE CREATE ON SCHEMA public FROM "{runtime_role}"')


async def main() -> None:
    owner_role, owner_password = _validated(
        "OWNER_DB_ROLE", "OWNER_DB_PASSWORD", "smart_owner"
    )
    runtime_role, runtime_password = _validated(
        "RUNTIME_DB_ROLE", "RUNTIME_DB_PASSWORD"
    )

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
            await bootstrap(
                conn, owner_role, owner_password, runtime_role, runtime_password
            )
    finally:
        await conn.close()
    print(
        f"bootstrap_db_role: roles {owner_role!r} (owner) and {runtime_role!r} (runtime) are ready"
    )


if __name__ == "__main__":
    asyncio.run(main())
