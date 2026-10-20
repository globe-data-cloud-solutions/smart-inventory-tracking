"""Rollback-only real-DB smoke check: ensure_inventory_partition(date) applies
RLS and the tenant_isolation policy to a partition only when they are missing
(S20b, D12 lock fix, migration 093).

The 092 body ran ALTER TABLE ... ENABLE ROW LEVEL SECURITY and DROP/CREATE
POLICY on every call, taking an ACCESS EXCLUSIVE lock on an existing partition
every time the worker ran. After 093 a call on a partition that already has
RLS and the policy changes nothing, so the policy oid stays the same.

Part A runs as the runtime role (DATABASE_URL, smart_runtime), ONE transaction,
rolled back:
  i.   first call on 2099-02 succeeds; record tenant_isolation oid
  ii.  second call: the policy oid is UNCHANGED

Part B runs as the partition owner (MIGRATION_DATABASE_URL), ONE transaction,
rolled back. The runtime role does not own the partition and cannot DROP
POLICY or ALTER it, so missing-policy / missing-RLS states can only be
simulated as the owner. The function call itself is the same.
  iii. DROP POLICY tenant_isolation, call again -> policy exists, RLS on
  iv.  DISABLE ROW LEVEL SECURITY, call again -> relrowsecurity true

Usage:
    set -a; source .env; set +a
    py -3.12 scripts/smoke_partition_idempotent.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BACKEND = _REPO_ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from shared.db.session import AsyncSessionLocal  # noqa: E402

_PARTITION = "inventory_transactions_2099_02"
_ENSURE_SQL = text("SELECT ensure_inventory_partition(date '2099-02-01')")
_POLICY_OID_SQL = text(
    "SELECT p.oid FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid "
    "WHERE c.relname = :n AND p.polname = 'tenant_isolation'"
)
_RLS_SQL = text("SELECT relrowsecurity FROM pg_class WHERE relname = :n")

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


async def _policy_oid(s):
    return (await s.execute(_POLICY_OID_SQL, {"n": _PARTITION})).scalar_one_or_none()


async def _rls(s):
    return (await s.execute(_RLS_SQL, {"n": _PARTITION})).scalar_one_or_none()


async def part_a() -> None:
    session = AsyncSessionLocal()
    try:
        who = (await session.execute(text(
            "SELECT current_user AS u, "
            "       (SELECT tableowner FROM pg_tables WHERE schemaname='public' "
            "        AND tablename='inventory_transactions') AS owner, "
            "       (SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user) AS bypass"
        ))).one()
        print(f"A: current_user={who.u} inventory_transactions_owner={who.owner} bypassrls={who.bypass}")
        _result(who.u != who.owner and not who.bypass, "A PRE: running as non-owner, NOBYPASSRLS role")

        first: dict[str, int | None] = {}

        async def step_i(s) -> bool:
            await s.execute(_ENSURE_SQL)
            first["oid"] = await _policy_oid(s)
            print(f"  i: tenant_isolation oid={first['oid']}")
            return first["oid"] is not None
        await _check(session, f"i: first call creates {_PARTITION} with tenant_isolation", step_i)

        async def step_ii(s) -> bool:
            await s.execute(_ENSURE_SQL)
            oid = await _policy_oid(s)
            print(f"  ii: tenant_isolation oid={oid} (before {first.get('oid')})")
            return oid is not None and oid == first.get("oid")
        await _check(session, "ii: second call leaves the policy oid unchanged", step_ii)
    finally:
        await session.rollback()
        await session.close()


async def part_b() -> None:
    engine = create_async_engine(os.environ["MIGRATION_DATABASE_URL"], pool_size=1, max_overflow=0)
    session = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)()
    try:
        who = (await session.execute(text(
            "SELECT current_user = (SELECT tableowner FROM pg_tables WHERE schemaname='public' "
            "AND tablename='inventory_transactions')"
        ))).scalar_one()
        _result(who is True, "B PRE: running as the inventory_transactions owner")

        async def setup(s) -> bool:
            await s.execute(_ENSURE_SQL)
            return await _policy_oid(s) is not None
        await _check(session, f"B setup: {_PARTITION} exists with tenant_isolation", setup)

        async def step_iii(s) -> bool:
            await s.execute(text(f"DROP POLICY tenant_isolation ON {_PARTITION}"))
            await s.execute(_ENSURE_SQL)
            oid, rls = await _policy_oid(s), await _rls(s)
            print(f"  iii: tenant_isolation oid={oid} relrowsecurity={rls}")
            return oid is not None and rls is True
        await _check(session, "iii: dropped policy is recreated, RLS still on", step_iii)

        async def step_iv(s) -> bool:
            await s.execute(text(f"ALTER TABLE {_PARTITION} DISABLE ROW LEVEL SECURITY"))
            await s.execute(_ENSURE_SQL)
            oid, rls = await _policy_oid(s), await _rls(s)
            print(f"  iv: tenant_isolation oid={oid} relrowsecurity={rls}")
            return oid is not None and rls is True
        await _check(session, "iv: disabled RLS is re-enabled", step_iv)
    finally:
        await session.rollback()
        await session.close()
        await engine.dispose()


async def main() -> None:
    await part_a()
    await part_b()
    print("SMOKE PASS" if not _failures else f"SMOKE FAIL ({len(_failures)} step(s) failed)")
    if _failures:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
