"""Behavioral tests for the SQLAlchemy resource boundary."""

from collections.abc import AsyncGenerator, Callable
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request

from verbaops.api.dependencies import get_database_session
from verbaops.api.lifespan import RuntimeResources
from verbaops.config.settings import Settings
from verbaops.db.resources import (
    DatabaseResourceError,
    create_database_resources,
    dispose_database_resources,
)


def database_settings() -> Settings:
    construct = cast(Callable[..., Settings], Settings)
    return construct(
        _env_file=None,
        database={"url": "postgresql+asyncpg://verbaops:secret@localhost/verbaops"},
    )


def test_database_resources_use_asyncpg_and_non_expiring_sessions() -> None:
    resources = create_database_resources(database_settings())

    assert resources.engine.url.drivername == "postgresql+asyncpg"
    assert resources.engine.pool._pre_ping is True
    assert resources.session_factory.kw["expire_on_commit"] is False
    assert resources.engine.echo is False


def test_non_async_database_url_is_rejected_without_secret() -> None:
    construct = cast(Callable[..., Settings], Settings)
    settings = construct(_env_file=None, database={"url": "postgresql://verbaops:secret@db/app"})

    with pytest.raises(DatabaseResourceError) as error:
        create_database_resources(settings)

    assert "secret" not in str(error.value)
    assert "postgresql" not in str(error.value)


@pytest.mark.asyncio
async def test_database_resources_are_disposed(monkeypatch: pytest.MonkeyPatch) -> None:
    resources = create_database_resources(database_settings())
    dispose = AsyncMock()
    monkeypatch.setattr(type(resources.engine), "dispose", dispose)

    await dispose_database_resources(resources)

    dispose.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_database_session_dependency_closes_session_after_success() -> None:
    class FakeSession:
        closed = False

        async def __aenter__(self) -> "FakeSession":
            return self

        async def __aexit__(self, *_: object) -> None:
            self.closed = True

    session = FakeSession()

    class Factory:
        def __call__(self) -> FakeSession:
            return session

    app = FastAPI()
    app.state.verbaops_runtime_resources = RuntimeResources(
        database=type("Database", (), {"session_factory": Factory()})(),
        redis=None,
    )
    request = Request({"type": "http", "app": app, "headers": [], "query_string": b""})

    iterator: AsyncGenerator[Any, None] = get_database_session(request)
    yielded = await anext(iterator)
    await iterator.aclose()

    assert yielded is session
    assert session.closed is True


@pytest.mark.asyncio
async def test_database_session_dependency_closes_session_after_downstream_failure() -> None:
    class FakeSession:
        closed = False

        async def __aenter__(self) -> "FakeSession":
            return self

        async def __aexit__(self, *_: object) -> None:
            self.closed = True

    session = FakeSession()

    class Factory:
        def __call__(self) -> FakeSession:
            return session

    app = FastAPI()
    app.state.verbaops_runtime_resources = RuntimeResources(
        database=type("Database", (), {"session_factory": Factory()})(),
        redis=None,
    )
    request = Request({"type": "http", "app": app, "headers": [], "query_string": b""})
    iterator = get_database_session(request)
    await anext(iterator)

    with pytest.raises(RuntimeError, match="downstream failure"):
        await iterator.athrow(RuntimeError("downstream failure"))

    assert session.closed is True
