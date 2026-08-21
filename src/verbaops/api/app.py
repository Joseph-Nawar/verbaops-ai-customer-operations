"""VerbaOps AI FastAPI application factory."""

from typing import Any, cast

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from verbaops import __version__
from verbaops.api.dependencies import ApplicationDependencies, RuntimeResourceUnavailableError
from verbaops.api.errors import (
    authentication_error_handler,
    http_exception_handler,
    runtime_resource_error_handler,
    validation_error_handler,
)
from verbaops.api.lifespan import lifespan
from verbaops.api.middleware import RequestContextMiddleware
from verbaops.api.routes.operations import router as operations_router
from verbaops.auth.provider import AuthenticationError, AuthProvider
from verbaops.config.settings import Settings
from verbaops.observability.logging import configure_logging


def create_app(*, settings: Settings, auth_provider: AuthProvider) -> FastAPI:
    """Create an independent VerbaOps AI FastAPI application instance."""

    configure_logging(settings)
    app = FastAPI(
        title="VerbaOps AI",
        version=__version__,
        description="VerbaOps AI multilingual customer-operations application foundation.",
        lifespan=lifespan,
    )
    app.state.verbaops_dependencies = ApplicationDependencies(
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
