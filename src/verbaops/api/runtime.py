"""Uvicorn composition root for the current Stage 1 runtime."""

from fastapi import FastAPI

from verbaops.api.app import create_app
from verbaops.auth.context import Role, TrustedContext
from verbaops.auth.development import DevelopmentAuthProvider
from verbaops.auth.provider import OpaqueCredential
from verbaops.config.settings import Environment, Settings


class RuntimeConfigurationError(RuntimeError):
    """Raised when runtime composition lacks a production identity provider."""


def create_runtime_app() -> FastAPI:
    """Load environment configuration and compose an application for Uvicorn factory mode."""

    settings = Settings()
    if settings.environment not in (Environment.DEVELOPMENT, Environment.TEST):
        raise RuntimeConfigurationError(
            "a production authentication provider is required for this environment"
        )
    context = TrustedContext(
        principal_id=settings.auth.development_principal_id,
        tenant_id=settings.auth.development_tenant_id,
        customer_id=settings.auth.development_customer_id,
        roles=frozenset({Role.CUSTOMER}),
    )
    provider = DevelopmentAuthProvider(
        {OpaqueCredential(settings.auth.development_token.get_secret_value()): context},
        environment=settings.environment,
    )
    return create_app(settings=settings, auth_provider=provider)
