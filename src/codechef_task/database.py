from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.engine import URL

from codechef_task.config import settings

database_url = URL.create(
    drivername="mysql+asyncmy",
    username=settings.db_user or None,
    password=settings.db_password or None,
    host=settings.db_host,
    port=settings.db_port,
    database=settings.db_name,
)

engine = create_async_engine(database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Yield a session and ensure it is closed after the request."""
    async with SessionLocal() as session:
        yield session
