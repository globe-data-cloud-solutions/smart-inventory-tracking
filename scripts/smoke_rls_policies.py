"""Rollback-only real-DB smoke check: tenant_isolation / audit policies and the
pre-auth lookup functions behave as migration 091 defines them (S20b, D1-D11).

Must run as the runtime role (smart_runtime: not the table owner, NOBYPASSRLS).
As the owner every RLS check passes vacuously, so the PRE step fails when the
current user owns `users`.

Everything happens in ONE transaction that is rolled back at the end: two
fixture tenants and one user in each are inserted, checked and discarded.
Each check runs in its own SAVEPOINT so an expected error does not abort the
rest. Tenant / SA context is set with transaction-local set_config directly,
so this tests the policies, not shared.db.rls.

Steps:
  i.   context tenant A: SELECT tenant B's users row -> 0 rows
  ii.  context tenant A: SELECT tenant A's users row -> 1 row
  iii. no context (tenant ''): SELECT both users rows -> 0 rows
  iv.  SA flag on, no tenant: SELECT both users rows -> 2 rows
  v.   context tenant B: INSERT audit_logs row with tenant A's id -> RLS rejects
  vi.  duplicate email (case-folded) in tenant B -> IntegrityError, uq_users_email_lower
  vii. no context: auth_user_by_email(:email) -> tenant A's user row

Usage:
    set -a; source .env; set +a
    py -3.12 scripts/smoke_rls_policies.py
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BACKEND = _REPO_ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import DBAPIError, IntegrityError  # noqa: E402

from shared.db.session import AsyncSessionLocal  # noqa: E402

_CTX_SQL = text(
    "SELECT set_config('app.current_tenant_id', :tid, true), "
    "       set_config('app.current_user_id',   :uid, true), "
    "       set_config('app.is_sa',             :sa,  true)"
)
_COUNT_USERS_SQL = text("SELECT count(*) FROM users WHERE id IN (:a, :b)")

_failures: list[str] = []


def _result(ok: bool, label: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'} {label}")
    if not ok:
        _failures.append(label)


async def _ctx(session, tenant_id: str, is_sa: bool = False) -> None:
    await session.execute(
        _CTX_SQL, {"tid": tenant_id, "uid": str(uuid.uuid4()), "sa": "on" if is_sa else "off"}
    )


async def _check(session, label: str, fn) -> None:
    """Run fn(session) -> bool inside a SAVEPOINT; an exception is a FAIL."""
    sp = await session.begin_nested()
    try:
        ok = await fn(session)
    except Exception as exc:  # noqa: BLE001 — every error is reported, not raised
        print(f"  {label}: {type(exc).__name__}: {str(exc).splitlines()[0][:200]}")
        ok = False
    finally:
        if sp.is_active:
            await sp.rollback()
    _result(ok, label)


async def main() -> None:
    session = AsyncSessionLocal()
    try:
        who = (await session.execute(text(
            "SELECT current_user AS u, "
            "       (SELECT tableowner FROM pg_tables WHERE schemaname='public' AND tablename='users') AS owner, "
            "       (SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user) AS bypass"
        ))).one()
        print(f"current_user={who.u} users_owner={who.owner} bypassrls={who.bypass}")
        _result(who.u != who.owner and not who.bypass, "PRE: running as non-owner, NOBYPASSRLS role")

        # ── fixtures (rolled back) ────────────────────────────────────────────
        tmpl = (await session.execute(text(
            "SELECT organisation_type, plan_id FROM tenants ORDER BY created_at LIMIT 1"
        ))).one()
        tag = uuid.uuid4().hex[:10]
        tenant_a, tenant_b = str(uuid.uuid4()), str(uuid.uuid4())
        user_a, user_b = str(uuid.uuid4()), str(uuid.uuid4())
        email_a = f"rls-smoke-a-{tag}@example.invalid"
        email_b = f"rls-smoke-b-{tag}@example.invalid"
        for tid, name in ((tenant_a, "A"), (tenant_b, "B")):
            await session.execute(
                text("INSERT INTO tenants (id, name, organisation_type, plan_id) "
                     "VALUES (:id, :name, :ot, :plan)"),
                {"id": tid, "name": f"rls-smoke-{name}-{tag}",
                 "ot": tmpl.organisation_type, "plan": tmpl.plan_id},
            )
        for tid, uid, email in ((tenant_a, user_a, email_a), (tenant_b, user_b, email_b)):
            await _ctx(session, tid)
            await session.execute(
                text("INSERT INTO users (id, tenant_id, email, full_name) "
                     "VALUES (:id, :tid, :email, 'RLS smoke')"),
                {"id": uid, "tid": tid, "email": email},
            )
        print(f"fixtures: tenant A={tenant_a} tenant B={tenant_b}")
        ids = {"a": user_a, "b": user_b}

        # i.
        async def step_i(s) -> bool:
            await _ctx(s, tenant_a)
            n = (await s.execute(text("SELECT count(*) FROM users WHERE id = :b"), ids)).scalar_one()
            print(f"  i: rows={n}")
            return n == 0
        await _check(session, "i: tenant A cannot see tenant B's user", step_i)

        # ii.
        async def step_ii(s) -> bool:
            await _ctx(s, tenant_a)
            n = (await s.execute(text("SELECT count(*) FROM users WHERE id = :a"), ids)).scalar_one()
            print(f"  ii: rows={n}")
            return n == 1
        await _check(session, "ii: tenant A sees its own user", step_ii)

        # iii.
        async def step_iii(s) -> bool:
            await _ctx(s, "")
            n = (await s.execute(_COUNT_USERS_SQL, ids)).scalar_one()
            print(f"  iii: rows={n}")
            return n == 0
        await _check(session, "iii: no tenant context sees no users", step_iii)

        # iv.
        async def step_iv(s) -> bool:
            await _ctx(s, "", is_sa=True)
            n = (await s.execute(_COUNT_USERS_SQL, ids)).scalar_one()
            print(f"  iv: rows={n}")
            return n == 2
        await _check(session, "iv: SA flag with no tenant sees both tenants", step_iv)

        # v.
        async def step_v(s) -> bool:
            await _ctx(s, tenant_b)
            try:
                await s.execute(
                    text("INSERT INTO audit_logs (tenant_id, action, decision) "
                         "VALUES (:tid, 'smoke:rls', 'ALLOW')"),
                    {"tid": tenant_a},
                )
            except DBAPIError as exc:
                msg = str(exc.orig)
                print(f"  v: rejected: {msg.splitlines()[0][:200]}")
                return "row-level security" in msg
            print("  v: INSERT accepted")
            return False
        await _check(session, "v: audit_logs INSERT into another tenant is rejected", step_v)

        # vi.
        async def step_vi(s) -> bool:
            await _ctx(s, tenant_b)
            try:
                await s.execute(
                    text("INSERT INTO users (tenant_id, email, full_name) "
                         "VALUES (:tid, :email, 'RLS smoke dup')"),
                    {"tid": tenant_b, "email": email_a.upper()},
                )
            except IntegrityError as exc:
                name = getattr(exc.orig.__cause__, "constraint_name", None) or getattr(
                    exc.orig, "constraint_name", None)
                print(f"  vi: IntegrityError constraint_name={name}")
                return name == "uq_users_email_lower"
            print("  vi: duplicate INSERT accepted")
            return False
        await _check(session, "vi: duplicate email across tenants -> uq_users_email_lower", step_vi)

        # vii.
        async def step_vii(s) -> bool:
            await _ctx(s, "")
            rows = (await s.execute(
                text("SELECT * FROM auth_user_by_email(:email)"), {"email": email_a.upper()}
            )).mappings().all()
            print(f"  vii: rows={len(rows)}")
            return len(rows) == 1 and str(rows[0]["id"]) == user_a
        await _check(session, "vii: auth_user_by_email works with no context", step_vii)
    finally:
        await session.rollback()
        await session.close()

    print("SMOKE PASS" if not _failures else f"SMOKE FAIL ({len(_failures)} step(s) failed)")
    if _failures:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
