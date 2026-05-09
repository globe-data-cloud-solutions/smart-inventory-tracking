from typing import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.rls import set_rls_context
from shared.db.session import AsyncReadSessionLocal, AsyncSessionLocal


async def get_db_session(user=Depends(lambda: None)) -> AsyncGenerator[AsyncSession, None]:  # noqa: B008
    async with AsyncSessionLocal() as session:
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
        await set_rls_context(session, user.tenant_id, user.user_id)
        yield session
