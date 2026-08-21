"""NovaCommerce operational API tests."""

from collections.abc import Callable
from typing import cast

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from novacommerce.api.app import create_app
from novacommerce.api.runtime import create_runtime_app
from novacommerce.config.settings import Settings


def make_settings() -> Settings:
    construct = cast(Callable[..., Settings], Settings)
    return construct(_env_file=None, service_token=SecretStr("test-token-" + "x" * 32))


async def request(app: FastAPI, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


@pytest.mark.asyncio
async def test_operational_endpoints_and_openapi() -> None:
    app = create_app(settings=make_settings())
    response = await request(app, "/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    response = await request(app, "/version")
    assert response.json() == {
        "service": "novacommerce",
        "version": "0.1.0",
        "environment": "development",
    }

    schema = (await request(app, "/openapi.json")).json()
    assert schema["info"]["title"] == "NovaCommerce Commerce Sandbox"
    assert "/v1/products/search" in schema["paths"]


@pytest.mark.asyncio
async def test_ready_returns_safe_503_when_database_is_unavailable() -> None:
    app = create_app(settings=make_settings())
    response = await request(app, "/ready")
    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": [{"name": "postgres", "status": "unavailable"}],
    }
    assert "secret" not in response.text


@pytest.mark.asyncio
async def test_ready_reports_database_health(monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app(settings=make_settings())
    app.state.novacommerce_runtime_resources = type("Resources", (), {"database": object()})()
    monkeypatch.setattr("novacommerce.api.routes.ping_database", _healthy_ping)
    response = await request(app, "/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": [{"name": "postgres", "status": "ok"}]}


async def _healthy_ping(_: object) -> bool:
    return True


def test_runtime_factory_composes_novacommerce_without_starting_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOVACOMMERCE_ENVIRONMENT", "test")
    monkeypatch.setenv(
        "NOVACOMMERCE_DATABASE__URL",
        "postgresql+asyncpg://user:password@localhost/commerce",
    )
    monkeypatch.setenv("NOVACOMMERCE_SERVICE_TOKEN", "test-token-" + "x" * 32)
    app = create_runtime_app()
    assert app.title == "NovaCommerce Commerce Sandbox"
