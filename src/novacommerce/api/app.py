"""NovaCommerce FastAPI application factory."""

from typing import Any, cast

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from novacommerce import __version__
from novacommerce.api.errors import APIError, api_error_handler, validation_error_handler
from novacommerce.api.lifespan import lifespan
from novacommerce.api.routes import router
from novacommerce.api.v1.router import router as v1_router
from novacommerce.config.settings import Settings


def create_app(*, settings: Settings) -> FastAPI:
    """Create operational routes and the authenticated read-only API."""

    token = settings.service_token
    if token is None or len(token.get_secret_value()) < 32 or not token.get_secret_value().strip():
        raise RuntimeError("NovaCommerce service token is required for the runtime application")

    app = FastAPI(title="NovaCommerce Commerce Sandbox", version=__version__, lifespan=lifespan)
    app.state.novacommerce_settings = settings
    app.add_exception_handler(APIError, cast(Any, api_error_handler))
    app.add_exception_handler(RequestValidationError, cast(Any, validation_error_handler))
    app.include_router(router)
    app.include_router(v1_router)
    return app
