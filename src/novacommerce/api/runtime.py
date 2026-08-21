"""Uvicorn factory for the NovaCommerce process."""

from fastapi import FastAPI

from novacommerce.api.app import create_app
from novacommerce.config.settings import Settings


def create_runtime_app() -> FastAPI:
    """Load NovaCommerce settings and compose the service application."""

    return create_app(settings=Settings())
