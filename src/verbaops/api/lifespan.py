"""FastAPI lifespan ownership for external runtime resources."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import httpx
from fastapi import FastAPI
from redis.asyncio import Redis

from verbaops.agent.runtime import AgentRuntime
from verbaops.api.dependencies import ApplicationDependencies
from verbaops.cache.redis import close_redis, create_redis_client
from verbaops.commerce.client import CommerceClient
from verbaops.conversations.service import ConversationService
from verbaops.db.resources import (
    DatabaseResources,
    create_database_resources,
    dispose_database_resources,
)
from verbaops.llm.litellm import LiteLLMClient


@dataclass(frozen=True, slots=True)
class RuntimeResources:
    """Mutable I/O resources owned by one application lifespan."""

    database: DatabaseResources | None = field(repr=False)
    redis: Redis | None = field(repr=False)
    llm_http_client: httpx.AsyncClient | None = field(default=None, repr=False)
    commerce_http_client: httpx.AsyncClient | None = field(default=None, repr=False)
    llm_client: LiteLLMClient | None = field(default=None, repr=False)
    commerce_client: CommerceClient | None = field(default=None, repr=False)
    conversation_service: ConversationService | None = field(default=None, repr=False)
    agent_runtime: AgentRuntime | None = field(default=None, repr=False)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create configured resources and guarantee cleanup, including partial startup."""

    dependencies = getattr(app.state, "verbaops_dependencies", None)
    if not isinstance(dependencies, ApplicationDependencies):
        raise RuntimeError("VerbaOps AI application dependencies are not configured")

    database: DatabaseResources | None = None
    redis: Redis | None = None
    llm_http_client: httpx.AsyncClient | None = None
    commerce_http_client: httpx.AsyncClient | None = None
    llm_client: LiteLLMClient | None = None
    commerce_client: CommerceClient | None = None
    conversation_service: ConversationService | None = None
    agent_runtime: AgentRuntime | None = None
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
        llm_http_client = httpx.AsyncClient()
        commerce_http_client = httpx.AsyncClient()
        llm_client = LiteLLMClient(dependencies.settings.llm, llm_http_client)
        commerce_client = CommerceClient(dependencies.settings.commerce, commerce_http_client)
        if database is not None:
            conversation_service = ConversationService(database.session_factory)
            agent_runtime = AgentRuntime(
                conversation_service=conversation_service,
                llm_client=llm_client,
                commerce_client=commerce_client,
            )
        app.state.verbaops_runtime_resources = RuntimeResources(
            database=database,
            redis=redis,
            llm_http_client=llm_http_client,
            commerce_http_client=commerce_http_client,
            llm_client=llm_client,
            commerce_client=commerce_client,
            conversation_service=conversation_service,
            agent_runtime=agent_runtime,
        )
        yield
    finally:
        app.state.verbaops_runtime_resources = None
        try:
            if commerce_http_client is not None:
                await commerce_http_client.aclose()
        finally:
            try:
                if llm_http_client is not None:
                    await llm_http_client.aclose()
            finally:
                try:
                    if redis is not None:
                        await close_redis(redis)
                finally:
                    if database is not None:
                        await dispose_database_resources(database)
