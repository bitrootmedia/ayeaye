"""Async engine + session factory.

`create_async_engine` doesn't connect eagerly, so importing this module is
cheap and safe without a live database.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(settings.database_url_async, future=True)

SessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    # Keep attributes accessible after commit() (e.g. for building responses)
    # instead of expiring and triggering a lazy reload on an async session.
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: one session per request, always closed."""
    async with SessionLocal() as session:
        yield session
