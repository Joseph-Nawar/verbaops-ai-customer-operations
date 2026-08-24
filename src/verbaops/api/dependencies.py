"""Typed FastAPI dependencies for application and runtime state."""

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from verbaops.auth.context import TrustedContext
from verbaops.auth.provider import AuthenticationError, AuthProvider, OpaqueCredential
from verbaops.config.settings import Settings
from verbaops.db.resources import DatabaseResources
from verbaops.observability.context import bind_tenant_id

if TYPE_CHECKING:
    from verbaops.agent.runtime import AgentRuntime
    from verbaops.conversations.service import ConversationService

if TYPE_CHECKING:
    from verbaops.api.lifespan import RuntimeResources


@dataclass(frozen=True, slots=True)
class ApplicationDependencies:
    """Immutable application dependencies currently required by M1C."""

    settings: Settings
    auth_provider: AuthProvider


class RuntimeResourceUnavailableError(RuntimeError):
    """Raised when a request asks for a resource not installed by lifespan."""


def get_runtime_resources(request: Request) -> "RuntimeResources":
    """Retrieve the lifespan-owned resource container."""

    from verbaops.api.lifespan import RuntimeResources

    resources = getattr(request.app.state, "verbaops_runtime_resources", None)
    if not isinstance(resources, RuntimeResources):
        raise RuntimeResourceUnavailableError("runtime resources are unavailable")
    return resources


async def get_database_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield one request-scoped session without implicit transaction commit."""

    resources = get_runtime_resources(request)
    database: DatabaseResources | None = resources.database
    if database is None:
        raise RuntimeResourceUnavailableError("database resource is unavailable")
    async with database.session_factory() as session:
        yield session


def get_redis_client(request: Request) -> Redis:
    """Retrieve the lifespan-owned Redis client."""

    resources = get_runtime_resources(request)
    if resources.redis is None:
        raise RuntimeResourceUnavailableError("redis resource is unavailable")
    return resources.redis


def get_conversation_service(request: Request) -> "ConversationService":
    """Retrieve the lifespan-owned conversation service."""

    resources = get_runtime_resources(request)
    if resources.conversation_service is None:
        raise RuntimeResourceUnavailableError("conversation service is unavailable")
    return resources.conversation_service


def get_agent_runtime(request: Request) -> "AgentRuntime":
    """Retrieve the lifespan-owned agent runtime."""

    resources = get_runtime_resources(request)
    if resources.agent_runtime is None:
        raise RuntimeResourceUnavailableError("agent runtime is unavailable")
    return resources.agent_runtime


def get_application_dependencies(request: Request) -> ApplicationDependencies:
    """Retrieve the immutable dependency container from application state."""

    dependencies = getattr(request.app.state, "verbaops_dependencies", None)
    if not isinstance(dependencies, ApplicationDependencies):
        raise RuntimeError("VerbaOps AI application dependencies are not configured")
    return dependencies


def get_settings(
    dependencies: Annotated[ApplicationDependencies, Depends(get_application_dependencies)],
) -> Settings:
    """Retrieve settings for the current application."""

    return dependencies.settings


def get_auth_provider(
    dependencies: Annotated[ApplicationDependencies, Depends(get_application_dependencies)],
) -> AuthProvider:
    """Retrieve the authentication provider for the current application."""

    return dependencies.auth_provider


bearer_scheme = HTTPBearer(auto_error=False)


async def get_trusted_context(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    auth_provider: Annotated[AuthProvider, Depends(get_auth_provider)],
) -> TrustedContext:
    """Authenticate one opaque Bearer credential into server-derived context."""

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError("authentication failed")

    context = auth_provider.authenticate(OpaqueCredential(credentials.credentials))
    bind_tenant_id(context.tenant_id)
    return context
