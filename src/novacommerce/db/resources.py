"""Lifespan-owned asynchronous PostgreSQL resources."""

import asyncio
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from novacommerce.config.settings import Settings


class DatabaseResourceError(RuntimeError):
    """Raised when NovaCommerce database resources cannot be configured."""


@dataclass(frozen=True, slots=True)
class DatabaseResources:
    """Engine and request-session factory owned by one service lifespan."""

    engine: AsyncEngine = field(repr=False)
    session_factory: async_sessionmaker[AsyncSession] = field(repr=False)


def create_database_resources(settings: Settings) -> DatabaseResources:
    """Create async PostgreSQL resources from a validated secret URL."""

    configured_url = settings.database.url
    if configured_url is None or not configured_url.get_secret_value().strip():
        raise DatabaseResourceError("database URL is not configured")
    url = configured_url.get_secret_value()
    if not url.startswith("postgresql+asyncpg://"):
        raise DatabaseResourceError("database URL must use the async PostgreSQL driver")
    try:
        engine = create_async_engine(url, pool_pre_ping=True, echo=False)
    except (SQLAlchemyError, ValueError) as error:
        raise DatabaseResourceError("database resources could not be created") from error
    return DatabaseResources(
        engine=engine,
        session_factory=async_sessionmaker(engine, expire_on_commit=False),
    )


async def ping_database(resources: DatabaseResources, *, timeout_seconds: float = 5.0) -> bool:
    """Return whether PostgreSQL answers a bounded SELECT 1 probe."""

    async def probe() -> None:
        async with resources.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(probe(), timeout=timeout_seconds)
    except Exception:
        return False
    return True


async def dispose_database_resources(resources: DatabaseResources) -> None:
    """Dispose the engine and its connection pool."""

    await resources.engine.dispose()
