import os
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_engine = create_async_engine(
    os.environ["DATABASE_URL"],
    pool_size=int(os.environ.get("DATABASE_POOL_SIZE", "20")),
    max_overflow=10,
    echo=False,
    future=True,
)

_read_engine = create_async_engine(
    os.environ["DATABASE_READ_URL"],
    pool_size=int(os.environ.get("DATABASE_POOL_SIZE", "20")),
    max_overflow=10,
    echo=False,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

AsyncReadSessionLocal = async_sessionmaker(
    bind=_read_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_write_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def get_read_session() -> AsyncGenerator[AsyncSession, None]:
    """Always routes to read replica — used by analytics, reports, AI ETL."""
    async with AsyncReadSessionLocal() as session:
        yield session
