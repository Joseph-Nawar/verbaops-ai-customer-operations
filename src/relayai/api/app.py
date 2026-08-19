"""RelayAI FastAPI application factory."""

from typing import Any, cast

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from relayai import __version__
from relayai.api.dependencies import ApplicationDependencies, RuntimeResourceUnavailableError
from relayai.api.errors import (
    authentication_error_handler,
    http_exception_handler,
    runtime_resource_error_handler,
    validation_error_handler,
)
from relayai.api.lifespan import lifespan
from relayai.api.middleware import RequestContextMiddleware
from relayai.api.routes.operations import router as operations_router
from relayai.auth.provider import AuthenticationError, AuthProvider
from relayai.config.settings import Settings
from relayai.observability.logging import configure_logging


def create_app(*, settings: Settings, auth_provider: AuthProvider) -> FastAPI:
    """Create an independent RelayAI FastAPI application instance."""

    configure_logging(settings)
    app = FastAPI(
        title="RelayAI",
        version=__version__,
        description="RelayAI multilingual customer-operations application foundation.",
        lifespan=lifespan,
    )
    app.state.relayai_dependencies = ApplicationDependencies(
        settings=settings,
        auth_provider=auth_provider,
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_exception_handler(AuthenticationError, cast(Any, authentication_error_handler))
    app.add_exception_handler(
        RuntimeResourceUnavailableError,
        cast(Any, runtime_resource_error_handler),
    )
    app.add_exception_handler(RequestValidationError, cast(Any, validation_error_handler))
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.include_router(operations_router)
    return app
