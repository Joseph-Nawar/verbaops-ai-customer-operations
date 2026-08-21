"""Uvicorn composition root for the current Stage 1 runtime."""

from fastapi import FastAPI

from verbaops.api.app import create_app
from verbaops.auth.development import DevelopmentAuthProvider
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
    provider = DevelopmentAuthProvider({}, environment=settings.environment)
    return create_app(settings=settings, auth_provider=provider)
