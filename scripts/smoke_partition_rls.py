"""Rollback-only real-DB smoke check: ensure_inventory_partition(date) creates an
inventory_transactions partition with tenant RLS when called by the runtime role
(S20b, D12, migration 092).

Must run as the runtime role (smart_runtime: not the table owner, NOBYPASSRLS),
which has no CREATE/ALTER rights of its own: the SECURITY DEFINER function is
the only way it can create a partition.

Everything happens in ONE transaction that is rolled back at the end, so the
2099-01 partition is discarded.

Steps:
  i.   SELECT ensure_inventory_partition(date '2099-01-01') -> no error
  ii.  second call -> no error (idempotent)
  iii. to_regclass('inventory_transactions_2099_01') is not null
  iv.  relrowsecurity is true on that partition
  v.   a tenant_isolation policy exists on it

Usage:
    set -a; source .env; set +a
    py -3.12 scripts/smoke_partition_rls.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BACKEND = _REPO_ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sqlalchemy import text  # noqa: E402

from shared.db.session import AsyncSessionLocal  # noqa: E402

_PARTITION = "inventory_transactions_2099_01"
_ENSURE_SQL = text("SELECT ensure_inventory_partition(date '2099-01-01')")

_failures: list[str] = []


def _result(ok: bool, label: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'} {label}")
    if not ok:
        _failures.append(label)


async def _check(session, label: str, fn) -> None:
    """Run fn(session) -> bool inside a SAVEPOINT; an exception is a FAIL.
    The savepoint is released on success so later steps see what it created."""
    sp = await session.begin_nested()
    try:
        ok = await fn(session)
    except Exception as exc:  # noqa: BLE001 — every error is reported, not raised
        print(f"  {label}: {type(exc).__name__}: {str(exc).splitlines()[0][:200]}")
        ok = False
    if sp.is_active:
        if ok:
            await sp.commit()
        else:
            await sp.rollback()
    _result(ok, label)


async def main() -> None:
    session = AsyncSessionLocal()
    try:
        who = (
            await session.execute(
                text(
                    "SELECT current_user AS u, "
                    "       (SELECT tableowner FROM pg_tables WHERE schemaname='public' "
                    "        AND tablename='inventory_transactions') AS owner, "
                    "       (SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user) AS bypass"
                )
            )
        ).one()
        print(
            f"current_user={who.u} inventory_transactions_owner={who.owner} bypassrls={who.bypass}"
        )
        _result(
            who.u != who.owner and not who.bypass,
            "PRE: running as non-owner, NOBYPASSRLS role",
        )

        async def step_i(s) -> bool:
            await s.execute(_ENSURE_SQL)
            return True

        await _check(
            session, "i: ensure_inventory_partition(2099-01-01) succeeds", step_i
        )

        async def step_ii(s) -> bool:
            await s.execute(_ENSURE_SQL)
            return True

        await _check(session, "ii: second call succeeds (idempotent)", step_ii)

        async def step_iii(s) -> bool:
            reg = (
                await s.execute(text("SELECT to_regclass(:n)::text"), {"n": _PARTITION})
            ).scalar_one()
            print(f"  iii: to_regclass={reg}")
            return reg is not None

        await _check(session, f"iii: {_PARTITION} exists", step_iii)

        async def step_iv(s) -> bool:
            rls = (
                await s.execute(
                    text("SELECT relrowsecurity FROM pg_class WHERE relname = :n"),
                    {"n": _PARTITION},
                )
            ).scalar_one_or_none()
            print(f"  iv: relrowsecurity={rls}")
            return rls is True

        await _check(session, f"iv: RLS enabled on {_PARTITION}", step_iv)

        async def step_v(s) -> bool:
            n = (
                await s.execute(
                    text(
                        "SELECT count(*) FROM pg_policies WHERE schemaname = 'public' "
                        "AND tablename = :n AND policyname = 'tenant_isolation'"
                    ),
                    {"n": _PARTITION},
                )
            ).scalar_one()
            print(f"  v: tenant_isolation policies={n}")
            return n == 1

        await _check(session, f"v: tenant_isolation policy on {_PARTITION}", step_v)
    finally:
        await session.rollback()
        await session.close()

    print(
        "SMOKE PASS"
        if not _failures
        else f"SMOKE FAIL ({len(_failures)} step(s) failed)"
    )
    if _failures:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
