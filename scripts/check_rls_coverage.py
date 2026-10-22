"""Catalog check: every table with a tenant_id column has tenant RLS, and FORCE is off.

Run after `alembic upgrade head`. Read-only and role-agnostic: it reads pg_class,
pg_attribute and pg_policy, which any role can see. Exits 1 on any violation.

Rules (CLAUDE.md, migrations 091 / 093 / 094):
  - every table or partition with a tenant_id column has
    relrowsecurity = true and a policy named tenant_isolation
  - relforcerowsecurity is false everywhere (D8: FORCE would also bind the owner)

Exemptions, each with its reason (keep this list short):
  outbox      global by design: the Celery worker polls across tenants (091 section 7)
  audit_logs  uses audit_select + audit_insert, not tenant_isolation (091 section 4);
              the append-only RULEs are checked by the migration tests instead

Usage:
    python scripts/check_rls_coverage.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import text  # noqa: E402

from shared.db.session import AsyncSessionLocal  # noqa: E402

EXEMPT = {
    "outbox": "global by design (091 section 7)",
}
# Tables whose tenant policy has a different name (091 section 4).
REQUIRED_POLICIES = {
    "audit_logs": {"audit_select", "audit_insert"},
}

COVERAGE_SQL = text(
    """
    SELECT c.relname AS table_name,
           c.relrowsecurity AS rls_enabled,
           c.relforcerowsecurity AS rls_forced,
           ARRAY(
               SELECT p.polname FROM pg_policy p WHERE p.polrelid = c.oid
           ) AS policies
    FROM pg_class c
    JOIN pg_attribute a
      ON a.attrelid = c.oid AND a.attname = 'tenant_id' AND NOT a.attisdropped
    WHERE c.relnamespace = 'public'::regnamespace
      AND c.relkind IN ('r', 'p')
    ORDER BY c.relname
    """
)


async def main() -> int:
    session = AsyncSessionLocal()
    try:
        rows = (await session.execute(COVERAGE_SQL)).fetchall()
    finally:
        await session.close()

    problems: list[str] = []
    for r in rows:
        if r.table_name in EXEMPT:
            continue
        required = REQUIRED_POLICIES.get(r.table_name, {"tenant_isolation"})
        missing = required - set(r.policies or [])
        if not r.rls_enabled or missing:
            problems.append(
                f"{r.table_name}: RLS enabled={r.rls_enabled} missing policies={sorted(missing)}"
            )
        if r.rls_forced:
            problems.append(
                f"{r.table_name}: FORCE ROW LEVEL SECURITY is on (D8 forbids it)"
            )

    print(f"checked {len(rows)} tenant-scoped tables/partitions")
    for p in problems:
        print(f"FAIL {p}")
    if not problems:
        print("PASS every tenant table has tenant_isolation and FORCE is off")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
