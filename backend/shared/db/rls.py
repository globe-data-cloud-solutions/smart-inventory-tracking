from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

# is_local = true: the setting lasts only until the current transaction ends,
# so it can never stay on a pooled connection and reach the next request.
_SET_RLS_SQL = text(
    "SELECT set_config('app.current_tenant_id', :tid, true), "
    "       set_config('app.current_user_id',   :uid, true)"
)


async def set_rls_context(
    session: AsyncSession, tenant_id: str, user_id: str
) -> None:
    """Must be called at the start of every request handler.
    Without this, RLS blocks all queries on tenant-scoped tables.

    The context is stored on the session and re-applied by _reapply_rls_context
    at the start of every later transaction, so it survives a mid-request commit.
    """
    session.info["rls"] = (str(tenant_id), str(user_id))
    await session.execute(_SET_RLS_SQL, {"tid": str(tenant_id), "uid": str(user_id)})


@event.listens_for(Session, "after_begin")
def _reapply_rls_context(session, transaction, connection) -> None:
    """Re-apply the session's tenant context to each new transaction."""
    rls = session.info.get("rls")
    if rls is None:
        return
    tenant_id, user_id = rls
    connection.execute(_SET_RLS_SQL, {"tid": tenant_id, "uid": user_id})
