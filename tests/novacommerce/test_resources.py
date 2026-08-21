"""NovaCommerce database resource tests."""

from collections.abc import Callable
from typing import cast

import pytest

from novacommerce.config.settings import Settings
from novacommerce.db.resources import (
    create_database_resources,
    dispose_database_resources,
    ping_database,
)


def make_settings(url: str = "postgresql+asyncpg://user:secret@localhost/commerce") -> Settings:
    construct = cast(Callable[..., Settings], Settings)
    return construct(_env_file=None, database={"url": url})


@pytest.mark.asyncio
async def test_database_resources_use_async_pre_ping_and_non_expiring_sessions() -> None:
    resources = create_database_resources(make_settings())
    try:
        assert resources.engine.pool._pre_ping is True
        assert resources.session_factory.kw["expire_on_commit"] is False
    finally:
        await dispose_database_resources(resources)


@pytest.mark.asyncio
async def test_ping_database_returns_false_when_connection_fails() -> None:
    class BrokenEngine:
        def connect(self) -> None:
            raise ConnectionError("not available")

    class Resources:
        engine = BrokenEngine()

    assert await ping_database(Resources(), timeout_seconds=0.01) is False  # type: ignore[arg-type]
