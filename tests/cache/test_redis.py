"""Behavioral tests for application-owned Redis resources."""

from collections.abc import Callable
from typing import cast
from unittest.mock import AsyncMock

import pytest

from relayai.cache.redis import (
    RedisResourceError,
    close_redis,
    create_redis_client,
    ping_redis,
)
from relayai.config.settings import Settings


def redis_settings(url: str = "redis://:secret@localhost:6379/0") -> Settings:
    construct = cast(Callable[..., Settings], Settings)
    return construct(_env_file=None, redis={"url": url})


def test_redis_resource_uses_configured_url_without_exposing_it() -> None:
    client = create_redis_client(redis_settings())

    assert client.connection_pool.connection_kwargs["host"] == "localhost"
    assert client.connection_pool.connection_kwargs["password"] == "secret"
    assert "secret" not in repr(client)


def test_malformed_redis_url_is_rejected_without_secret() -> None:
    with pytest.raises(RedisResourceError) as error:
        create_redis_client(redis_settings("not-a-redis-url-with-secret"))

    assert "secret" not in str(error.value)
    assert "not-a-redis" not in str(error.value)


@pytest.mark.asyncio
async def test_redis_ping_and_close_are_explicit() -> None:
    client = AsyncMock()
    client.ping.return_value = True

    assert await ping_redis(client) is True
    await close_redis(client)

    client.ping.assert_awaited_once()
    client.aclose.assert_awaited_once()
