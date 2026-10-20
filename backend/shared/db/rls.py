"""Tenant context for PostgreSQL row-level security (S20b, migration 091).

The app connects as the runtime role (not the table owner, NOBYPASSRLS), so
every tenant-scoped table is filtered by its tenant_isolation policy:

    tenant_id = NULLIF(app.current_tenant_id, '')::uuid OR app.is_sa = 'on'

Three settings carry the context, all transaction-local (is_local = true):
  app.current_tenant_id  the caller's tenant; '' or unset matches no rows
  app.current_user_id    the caller, for audit
  app.is_sa              'on' for SA requests and system jobs (cross-tenant),
                         otherwise explicitly 'off'

is_local = true means a setting lasts only until the current transaction ends,
so it can never stay on a pooled connection and reach the next request. The
context is stored in session.info["rls"] and re-applied by an after_begin
listener at the start of every later transaction, so it survives a mid-request
commit.

Background work with no user and no single tenant (Celery maintenance tasks)
uses set_system_rls_context: empty tenant, SA flag on, labelled with the task.
Pre-auth lookups (login, password reset) go through the SECURITY DEFINER
auth_* functions instead of any context.
"""
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

_SET_RLS_SQL = text(
    "SELECT set_config('app.current_tenant_id', :tid, true), "
    "       set_config('app.current_user_id',   :uid, true), "
    "       set_config('app.is_sa',             :sa,  true)"
)

SYSTEM_USER_ID = ""


def _params(tenant_id: str, user_id: str, is_sa: bool) -> dict:
    return {"tid": tenant_id, "uid": user_id, "sa": "on" if is_sa else "off"}


async def set_rls_context(
    session: AsyncSession, tenant_id: str, user_id: str, is_sa: bool = False
) -> None:
    """Must be called at the start of every request handler.
    Without this, RLS blocks all queries on tenant-scoped tables.

    is_sa=True (SA callers only) lets the session see every tenant's rows.
    The context is stored on the session and re-applied by _reapply_rls_context
    at the start of every later transaction, so it survives a mid-request commit.
    """
    # None (SA has no tenant) binds as '', never the string 'None'.
    rls = ("" if tenant_id is None else str(tenant_id), str(user_id), bool(is_sa))
    session.info["rls"] = rls
    await session.execute(_SET_RLS_SQL, _params(*rls))


async def set_system_rls_context(session: AsyncSession, label: str) -> None:
    """Context for background work that spans tenants: no tenant, SA flag on.
    label (the task name) is kept in session.info["rls_label"] for diagnosis."""
    rls = ("", SYSTEM_USER_ID, True)
    session.info["rls"] = rls
    session.info["rls_label"] = label
    await session.execute(_SET_RLS_SQL, _params(*rls))


@event.listens_for(Session, "after_begin")
def _reapply_rls_context(session, transaction, connection) -> None:
    """Re-apply the session's tenant context to each new transaction."""
    rls = session.info.get("rls")
    if rls is None:
        return
    connection.execute(_SET_RLS_SQL, _params(*rls))
