"""Shared helpers for the seeding scripts in this directory.

Used by seed_dev_sample.py (dev: full sample tenants + SA) and
bootstrap_sa_account.py (stage/prod: SA only, no tenants — seed_enabled=false
there, so nothing else ever creates the SA account in those environments).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import asyncpg
import bcrypt

FIXTURE = Path(__file__).resolve().parent / "seed" / "dev_sample_tenants.json"
SA_EMAIL = "smartadmin@smart-inventory.com"


_SSL_ALIASES = {
    "true": "require",
    "1": "require",
    "on": "require",
    "false": "disable",
    "0": "disable",
    "off": "disable",
}


def _ssl_mode(query: str) -> str:
    """SSL mode for asyncpg, taken from the URL's ?ssl= or ?sslmode= query.

    An explicit value in the URL wins (the AWS URLs carry ?ssl=require). With
    no value, a local developer database gets "prefer" (SSL if the server
    offers it, plain otherwise); every other environment gets "require", so a
    URL that loses its query still refuses a non-SSL connection.
    """
    params = parse_qs(query)
    raw = (params.get("ssl") or params.get("sslmode") or [""])[0].strip().lower()
    if raw:
        return _SSL_ALIASES.get(raw, raw)
    return "prefer" if os.environ.get("ENVIRONMENT") == "local" else "require"


def connect_kwargs(url: str) -> dict:
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
        "ssl": _ssl_mode(parts.query),
    }


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


async def insert_row(conn: asyncpg.Connection, table: str, row: dict) -> None:
    # json_populate_record coerces each JSON value to the column's own type
    # (uuid, timestamptz, enum, arrays, jsonb), so the fixture stays plain JSON.
    # The table name comes from the fixture and is double-quoted.
    await conn.execute(
        f'INSERT INTO "{table}" SELECT (json_populate_record(NULL::"{table}", $1::json)).* '
        "ON CONFLICT DO NOTHING",
        json.dumps(row),
    )


def load_sa_row() -> dict:
    """The SA user's fixture row (tenant_id IS NULL), shape only — password_hash
    is filled in by the caller from a runtime-provided password, never from
    the fixture file."""
    fixture: dict[str, list[dict]] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return next(r for r in fixture["users"] if r["email"] == SA_EMAIL)
