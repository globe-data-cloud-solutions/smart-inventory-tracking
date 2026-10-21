"""Resolve the database URL Alembic migrations connect with.

Migrations run as the owner role (MIGRATION_DATABASE_URL), which creates and
owns the schema objects. DATABASE_URL is the runtime role: it has no CREATE
privilege, and if it ever ran migrations it would own the tables and so bypass
RLS. The fallback to DATABASE_URL is therefore allowed only for ENVIRONMENT=local.
"""

import os
import sys
from collections.abc import Mapping


def migration_database_url(environ: Mapping[str, str]) -> str:
    url = environ.get("MIGRATION_DATABASE_URL", "")
    if url:
        return url
    if environ.get("ENVIRONMENT", "") == "local":
        fallback = environ.get("DATABASE_URL", "")
        if fallback:
            return fallback
        raise RuntimeError(
            "Set MIGRATION_DATABASE_URL or DATABASE_URL to run migrations locally."
        )
    raise RuntimeError(
        "MIGRATION_DATABASE_URL is required to run migrations outside ENVIRONMENT=local; "
        "refusing to fall back to DATABASE_URL (the runtime role)."
    )


def migration_database_url_or_exit(prog: str) -> str:
    """Same rule for the seed and SA scripts, exiting with a message instead of raising."""
    try:
        return migration_database_url(os.environ)
    except RuntimeError as exc:
        sys.exit(f"{prog}: {exc}")
