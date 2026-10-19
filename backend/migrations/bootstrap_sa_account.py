"""Create the SA account only, for environments where seed_enabled=false.

stage and prod never run seed_dev_sample.py (SEED_ENABLED=false there, per
CLAUDE.md's 2026-10-17 dev-sample-data decision), so a fresh RDS in those
environments has no SA account at all. This script creates ONLY the SA user
row — no tenants, no sample data — reusing the same insert/hash helpers as
seed_dev_sample.py (backend/migrations/seed_common.py).

Intended to run as a one-off task against the existing migration image,
overriding its command, e.g.:

    aws ecs run-task \\
      --cluster smart-<env> \\
      --task-definition smart-<env>-migrate \\
      --overrides '{"containerOverrides": [{
        "name": "migrate",
        "command": ["python", "/app/backend/migrations/bootstrap_sa_account.py",
                     "--email-secret-name", "smart/<env>/sa/email",
                     "--password-secret-name", "smart/<env>/sa/password"]
      }]}'

See docs/claude/redeploy-runbook.md and docs/claude/ci-cd.md for the full
invocation and the IAM/Terraform this needs (not added by this script).

Idempotency: the email is looked up first; if a user with that email already
exists, nothing is written and nothing is changed — this never overwrites an
existing SA's password. Safe to re-run.

Secrets: the SA's email and password are never hardcoded and never logged —
only the Secrets Manager SECRET NAMES are passed in (as CLI args or the
SA_EMAIL_SECRET_NAME / SA_PASSWORD_SECRET_NAME env vars); this script fetches
the actual values from Secrets Manager at runtime via boto3. The IAM role
running this task needs secretsmanager:GetSecretValue on both secret ARNs
(Terraform change, not made here — see the runbook doc).

Environment / arguments:
  --email-secret-name / SA_EMAIL_SECRET_NAME        Secrets Manager secret name holding the SA email
  --password-secret-name / SA_PASSWORD_SECRET_NAME  Secrets Manager secret name holding the SA password
  DATABASE_URL                                      runtime role (smart_runtime), SQLAlchemy or libpq form
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

import asyncpg

from migrations.seed_common import connect_kwargs, hash_password, insert_row, load_sa_row


def _get_secret_value(secret_name: str) -> str:
    import boto3  # lazy import, matches shared/storage/s3.py and shared/email/sender.py

    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=secret_name)
    return response["SecretString"]


def _resolve_arg(cli_value: str | None, env_var: str, secret_name_label: str) -> str:
    name = cli_value or os.environ.get(env_var, "")
    if not name:
        sys.exit(f"bootstrap_sa_account: missing {secret_name_label} (pass it or set {env_var})")
    return name


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email-secret-name", default=None)
    parser.add_argument("--password-secret-name", default=None)
    return parser.parse_args(argv)


async def bootstrap(email: str, password: str, database_url: str) -> bool:
    """Returns True if the SA was created, False if it already existed."""
    sa_row = load_sa_row()
    conn = await asyncpg.connect(**connect_kwargs(database_url))
    try:
        async with conn.transaction():
            if await conn.fetchval("SELECT 1 FROM users WHERE email = $1", email):
                return False
            await insert_row(
                conn, "users",
                {**sa_row, "email": email, "password_hash": hash_password(password)},
            )
            return True
    finally:
        await conn.close()


async def main() -> None:
    args = parse_args(sys.argv[1:])
    email_secret_name = _resolve_arg(
        args.email_secret_name, "SA_EMAIL_SECRET_NAME", "--email-secret-name"
    )
    password_secret_name = _resolve_arg(
        args.password_secret_name, "SA_PASSWORD_SECRET_NAME", "--password-secret-name"
    )
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        sys.exit("bootstrap_sa_account: missing required env var DATABASE_URL")

    email = _get_secret_value(email_secret_name)
    password = _get_secret_value(password_secret_name)

    created = await bootstrap(email, password, database_url)
    # Never log the email or password values themselves.
    print("bootstrap_sa_account: SA created." if created else "bootstrap_sa_account: SA already exists — skipped.")


if __name__ == "__main__":
    asyncio.run(main())
