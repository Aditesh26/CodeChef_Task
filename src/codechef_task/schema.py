"""Non-destructive initial schema creation."""

from sqlalchemy.ext.asyncio import AsyncEngine

from codechef_task.database import engine
from codechef_task.models import Base


async def initialize_schema(target_engine: AsyncEngine = engine) -> None:
    """Create missing tables without dropping or replacing existing tables."""
    async with target_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
