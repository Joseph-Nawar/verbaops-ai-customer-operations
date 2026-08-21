"""Typed FastAPI dependencies for NovaCommerce runtime state."""

from collections.abc import AsyncGenerator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from novacommerce.db.resources import DatabaseResources


class RuntimeResourceUnavailableError(RuntimeError):
    """Raised when a request needs a resource not installed by lifespan."""


def get_database_resources(request: Request) -> DatabaseResources:
    """Retrieve lifespan-owned database resources."""

    resources = getattr(request.app.state, "novacommerce_runtime_resources", None)
    database = getattr(resources, "database", None)
    if not isinstance(database, DatabaseResources):
        raise RuntimeResourceUnavailableError("database resource is unavailable")
    return database


async def get_database_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield one request-scoped session without implicit commit."""

    resources = get_database_resources(request)
    async with resources.session_factory() as session:
        yield session
