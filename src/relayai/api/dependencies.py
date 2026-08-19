"""Typed FastAPI dependencies for application state and authentication."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from relayai.auth.context import TrustedContext
from relayai.auth.provider import AuthenticationError, AuthProvider, OpaqueCredential
from relayai.config.settings import Settings
from relayai.observability.context import bind_tenant_id


@dataclass(frozen=True, slots=True)
class ApplicationDependencies:
    """Immutable application dependencies currently required by M1C."""

    settings: Settings
    auth_provider: AuthProvider


def get_application_dependencies(request: Request) -> ApplicationDependencies:
    """Retrieve the immutable dependency container from application state."""

    dependencies = getattr(request.app.state, "relayai_dependencies", None)
    if not isinstance(dependencies, ApplicationDependencies):
        raise RuntimeError("RelayAI application dependencies are not configured")
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
