from typing import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.rls import set_rls_context
from shared.db.session import AsyncReadSessionLocal, AsyncSessionLocal


async def get_db_session(user=Depends(lambda: None)) -> AsyncGenerator[AsyncSession, None]:  # noqa: B008
    async with AsyncSessionLocal() as session:
        # Guard against None user: @require_permission raises 401 for unauthenticated
        # requests before the handler executes, so it is safe to skip RLS context here.
        # Skipping rather than crashing ensures the 401 error response is returned
        # cleanly instead of a 500 from an AttributeError on user.tenant_id.
        if user is not None:
            await set_rls_context(session, user.tenant_id, user.user_id)
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_read_db_session(user=Depends(lambda: None)) -> AsyncGenerator[AsyncSession, None]:  # noqa: B008
    """Read replica session — use for analytics, reports, and AI ETL queries only."""
    async with AsyncReadSessionLocal() as session:
        if user is not None:
            await set_rls_context(session, user.tenant_id, user.user_id)
        yield session
