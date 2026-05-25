from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def set_rls_context(
    session: AsyncSession, tenant_id: str, user_id: str
) -> None:
    """Must be called at the start of every request handler.
    Without this, RLS blocks all queries on tenant-scoped tables.
    """
    await session.execute(
        text(
            "SELECT set_config('app.current_tenant_id', :tid, false), "
            "       set_config('app.current_user_id',   :uid, false)"
        ),
        {"tid": tenant_id, "uid": user_id},
    )
