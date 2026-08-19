"""FastAPI lifespan ownership for external runtime resources."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from fastapi import FastAPI
from redis.asyncio import Redis

from relayai.api.dependencies import ApplicationDependencies
from relayai.cache.redis import close_redis, create_redis_client
from relayai.db.resources import (
    DatabaseResources,
    create_database_resources,
    dispose_database_resources,
)


@dataclass(frozen=True, slots=True)
class RuntimeResources:
    """Mutable I/O resources owned by one application lifespan."""

    database: DatabaseResources | None = field(repr=False)
    redis: Redis | None = field(repr=False)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create configured resources and guarantee cleanup, including partial startup."""

    dependencies = getattr(app.state, "relayai_dependencies", None)
    if not isinstance(dependencies, ApplicationDependencies):
        raise RuntimeError("RelayAI application dependencies are not configured")

    database: DatabaseResources | None = None
    redis: Redis | None = None
    try:
        if (
            dependencies.settings.database.url is not None
            and dependencies.settings.database.url.get_secret_value().strip()
        ):
            database = create_database_resources(dependencies.settings)
        if (
            dependencies.settings.redis.url is not None
            and dependencies.settings.redis.url.get_secret_value().strip()
        ):
            redis = create_redis_client(dependencies.settings)
        app.state.relayai_runtime_resources = RuntimeResources(database=database, redis=redis)
        yield
    finally:
        app.state.relayai_runtime_resources = None
        try:
            if redis is not None:
                await close_redis(redis)
        finally:
            if database is not None:
                await dispose_database_resources(database)
