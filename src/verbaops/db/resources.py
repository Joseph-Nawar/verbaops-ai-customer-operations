"""Application-owned asynchronous SQLAlchemy resources."""

import asyncio
from dataclasses import dataclass, field
from typing import Final

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from verbaops.config.settings import Settings

_ASYNC_POSTGRES_SCHEME: Final = "postgresql+asyncpg"


class DatabaseResourceError(RuntimeError):
    """Raised when database resources cannot be created safely."""


@dataclass(frozen=True, slots=True)
class DatabaseResources:
    """Engine and request-session factory owned by one application lifespan."""

    engine: AsyncEngine = field(repr=False)
    session_factory: async_sessionmaker[AsyncSession] = field(repr=False)


def create_database_resources(settings: Settings) -> DatabaseResources:
    """Create asyncpg resources from a validated, secret-bearing URL."""

    configured_url = settings.database.url
    if configured_url is None or not configured_url.get_secret_value().strip():
        raise DatabaseResourceError("database URL is not configured")

    url = configured_url.get_secret_value()
    if not url.startswith(f"{_ASYNC_POSTGRES_SCHEME}://"):
        raise DatabaseResourceError("database URL must use the async PostgreSQL driver")

    try:
        engine = create_async_engine(url, pool_pre_ping=True, echo=False)
    except (SQLAlchemyError, ValueError) as error:
        raise DatabaseResourceError("database resources could not be created") from error

    return DatabaseResources(
        engine=engine,
        session_factory=async_sessionmaker(engine, expire_on_commit=False),
    )


async def ping_database(resources: DatabaseResources, *, timeout_seconds: float = 2.0) -> bool:
    """Return whether the database answers a bounded `SELECT 1` probe."""

    async def _probe() -> None:
        async with resources.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(_probe(), timeout=timeout_seconds)
    except Exception:
        return False
    return True


async def dispose_database_resources(resources: DatabaseResources) -> None:
    """Dispose the lifespan-owned engine and its connection pool."""

    await resources.engine.dispose()
