"""Read-only real-DB smoke check: the RLS tenant context must not outlive the
request that set it.

Drives the real get_db_session generator (backend/shared/db/dependencies.py)
against the real AsyncSessionLocal pool, the same way FastAPI does: anext()
to open the session, then asend(None) / athrow() to finish it. The generator
COMMITS on the success path — a rollback would revert a session-level
set_config and hide the leak, so the leak check has to go through a commit.

Writes nothing: every statement is a SELECT, so the commits are no-op
transactions. pg_backend_pid() is printed with every check to show the new
session really reused the pooled connection the previous request used.

Steps:
  1. Request with tenant A: SELECT 1, generator commits and returns normally.
  2. NEW session from the pool: app.current_tenant_id must be NULL or ''.
  3. Request with tenant A that commits mid-request: the next statement must
     still see tenant A (after_begin re-applies the context).
  4. Request that raises after set_rls_context: the next NEW session must see
     NULL or ''.

Usage:
    set -a; source .env; set +a
    python scripts/smoke_rls_context.py
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BACKEND = _REPO_ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sqlalchemy import text  # noqa: E402

from shared.db.dependencies import get_db_session  # noqa: E402
from shared.db.session import AsyncSessionLocal  # noqa: E402

_SETTING_SQL = text(
    "SELECT current_setting('app.current_tenant_id', true) AS tid, pg_backend_pid() AS pid"
)

_failures: list[str] = []


def _result(ok: bool, label: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'} {label}")
    if not ok:
        _failures.append(label)


async def _finish(gen) -> bool:
    """Let the dependency generator run its commit; True if it returned normally."""
    try:
        await gen.asend(None)
    except StopAsyncIteration:
        return True
    return False


async def _new_session_setting() -> tuple[str | None, int]:
    async with AsyncSessionLocal() as session:
        row = (await session.execute(_SETTING_SQL)).one()
        return row.tid, row.pid


async def main() -> None:
    async with AsyncSessionLocal() as session:
        tenant_a = str(
            (await session.execute(text("SELECT id FROM tenants LIMIT 1"))).scalar_one()
        )
    user = SimpleNamespace(tenant_id=tenant_a, user_id=str(uuid.uuid4()))
    print(f"tenant A = {tenant_a}")

    # 1. request with tenant A, committed by the generator
    gen = get_db_session(user=user)
    session = await anext(gen)
    one = (await session.execute(text("SELECT 1"))).scalar_one()
    pid = (await session.execute(text("SELECT pg_backend_pid()"))).scalar_one()
    returned = await _finish(gen)
    print(
        f"step 1: SELECT 1 -> {one}, pid={pid}, generator returned normally={returned}"
    )
    _result(one == 1 and returned, "step 1: request committed and returned normally")

    # 2. a NEW session must not inherit tenant A
    tid, pid2 = await _new_session_setting()
    print(f"step 2: current_setting('app.current_tenant_id') = {tid!r}, pid={pid2}")
    _result(
        tid in (None, ""), "step 2: new session sees NULL/'' after committed request"
    )

    # 3. mid-request commit keeps tenant A for the next statement
    gen = get_db_session(user=user)
    session = await anext(gen)
    await session.execute(text("SELECT 1"))
    await session.commit()
    row = (await session.execute(_SETTING_SQL)).one()
    returned = await _finish(gen)
    print(
        f"step 3: after mid-request commit current_setting = {row.tid!r}, pid={row.pid}, "
        f"generator returned normally={returned}"
    )
    _result(
        row.tid == tenant_a and returned,
        "step 3: tenant A still set after mid-request commit",
    )

    # 4. exception path: the generator rolls back and re-raises
    gen = get_db_session(user=user)
    session = await anext(gen)
    await session.execute(text("SELECT 1"))
    try:
        await gen.athrow(RuntimeError("smoke: handler failure"))
        raised = False
    except RuntimeError:
        raised = True
    tid, pid4 = await _new_session_setting()
    print(
        f"step 4: generator re-raised={raised}; new session current_setting = {tid!r}, pid={pid4}"
    )
    _result(
        raised and tid in (None, ""),
        "step 4: new session sees NULL/'' after failed request",
    )

    print(
        "SMOKE PASS"
        if not _failures
        else f"SMOKE FAIL ({len(_failures)} step(s) failed)"
    )
    if _failures:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
