"""Behavioral tests for lifespan-owned runtime resources."""

from collections.abc import Callable
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI

from relayai.api.dependencies import ApplicationDependencies
from relayai.api.lifespan import lifespan
from relayai.auth.development import DevelopmentAuthProvider
from relayai.config.settings import Settings


@pytest.mark.asyncio
async def test_lifespan_installs_and_cleans_runtime_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    construct = cast(Callable[..., Settings], Settings)
    settings = construct(
        _env_file=None,
        database={"url": "postgresql+asyncpg://relayai:secret@db/app"},
        redis={"url": "redis://redis:6379/0"},
    )
    app = FastAPI()
    app.state.relayai_dependencies = ApplicationDependencies(
        settings=settings,
        auth_provider=DevelopmentAuthProvider({}, environment=settings.environment),
    )
    engine = AsyncMock()
    redis = AsyncMock()
    database = type("Database", (), {"engine": engine})()
    dispose = AsyncMock()
    close = AsyncMock()
    monkeypatch.setattr("relayai.api.lifespan.create_database_resources", lambda _: database)
    monkeypatch.setattr("relayai.api.lifespan.create_redis_client", lambda _: redis)
    monkeypatch.setattr("relayai.api.lifespan.dispose_database_resources", dispose)
    monkeypatch.setattr("relayai.api.lifespan.close_redis", close)

    async with lifespan(app):
        assert app.state.relayai_runtime_resources.database is database
        assert app.state.relayai_runtime_resources.redis is redis
    assert app.state.relayai_runtime_resources is None
    close.assert_awaited_once_with(redis)
    dispose.assert_awaited_once_with(database)


@pytest.mark.asyncio
async def test_lifespan_cleans_partial_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    construct = cast(Callable[..., Settings], Settings)
    settings = construct(
        _env_file=None,
        database={"url": "postgresql+asyncpg://relayai:secret@db/app"},
        redis={"url": "redis://redis:6379/0"},
    )
    app = FastAPI()
    app.state.relayai_dependencies = ApplicationDependencies(
        settings=settings,
        auth_provider=DevelopmentAuthProvider({}, environment=settings.environment),
    )
    database = type("Database", (), {"engine": object()})()
    dispose = AsyncMock()
    close = AsyncMock()
    monkeypatch.setattr("relayai.api.lifespan.create_database_resources", lambda _: database)
    monkeypatch.setattr(
        "relayai.api.lifespan.create_redis_client",
        lambda _: (_ for _ in ()).throw(RuntimeError("redis unavailable")),
    )
    monkeypatch.setattr("relayai.api.lifespan.dispose_database_resources", dispose)
    monkeypatch.setattr("relayai.api.lifespan.close_redis", close)

    with pytest.raises(RuntimeError, match="redis unavailable"):
        async with lifespan(app):
            pass

    dispose.assert_awaited_once_with(database)
    close.assert_not_awaited()
