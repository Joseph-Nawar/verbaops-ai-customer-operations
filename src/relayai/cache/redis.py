"""Application-lifespan-owned asynchronous Redis resource."""

import asyncio
from urllib.parse import urlsplit

from redis.asyncio import Redis

from relayai.config.settings import Settings


class RedisResourceError(RuntimeError):
    """Raised when a Redis resource cannot be created safely."""


def create_redis_client(settings: Settings) -> Redis:
    """Create one Redis client from the validated application configuration."""

    configured_url = settings.redis.url
    if configured_url is None or not configured_url.get_secret_value().strip():
        raise RedisResourceError("redis URL is not configured")

    url = configured_url.get_secret_value()
    parsed = urlsplit(url)
    if parsed.scheme not in {"redis", "rediss"} or not parsed.netloc:
        raise RedisResourceError("redis URL is malformed")

    try:
        return Redis.from_url(url)
    except (TypeError, ValueError) as error:
        raise RedisResourceError("redis resources could not be created") from error


async def ping_redis(client: Redis, *, timeout_seconds: float = 2.0) -> bool:
    """Return whether Redis answers a bounded ping probe."""

    try:
        await asyncio.wait_for(client.ping(), timeout=timeout_seconds)
    except Exception:
        return False
    return True


async def close_redis(client: Redis) -> None:
    """Explicitly close a lifespan-owned Redis client."""

    await client.aclose()
