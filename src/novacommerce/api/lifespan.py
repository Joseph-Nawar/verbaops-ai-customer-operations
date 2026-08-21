"""FastAPI lifespan ownership for NovaCommerce PostgreSQL."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from fastapi import FastAPI

from novacommerce.config.settings import Settings
from novacommerce.db.resources import (
    DatabaseResources,
    create_database_resources,
    dispose_database_resources,
)


@dataclass(frozen=True, slots=True)
class RuntimeResources:
    """Resources owned by one NovaCommerce application lifespan."""

    database: DatabaseResources | None = field(repr=False)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create configured database resources and always dispose partial startup."""

    settings = getattr(app.state, "novacommerce_settings", None)
    if not isinstance(settings, Settings):
        raise RuntimeError("NovaCommerce settings are not configured")
    database: DatabaseResources | None = None
    try:
        if settings.database.url is not None and settings.database.url.get_secret_value().strip():
            database = create_database_resources(settings)
        app.state.novacommerce_runtime_resources = RuntimeResources(database=database)
        yield
    finally:
        app.state.novacommerce_runtime_resources = None
        if database is not None:
            await dispose_database_resources(database)
