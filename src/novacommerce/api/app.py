"""NovaCommerce FastAPI application factory."""

from fastapi import FastAPI

from novacommerce import __version__
from novacommerce.api.lifespan import lifespan
from novacommerce.api.routes import router
from novacommerce.config.settings import Settings


def create_app(*, settings: Settings) -> FastAPI:
    """Create an operational-only NovaCommerce application."""

    app = FastAPI(title="NovaCommerce Commerce Sandbox", version=__version__, lifespan=lifespan)
    app.state.novacommerce_settings = settings
    app.include_router(router)
    return app
