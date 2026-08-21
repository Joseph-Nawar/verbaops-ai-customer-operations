"""Readiness behavior tests for real runtime dependencies."""

from collections.abc import Callable
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI

from verbaops.api.app import create_app
from verbaops.config.settings import Settings

from .conftest import build_provider, request


def configured_settings() -> Settings:
    construct = cast(Callable[..., Settings], Settings)
    return construct(
        _env_file=None,
        database={"url": "postgresql+asyncpg://verbaops:secret@db/app"},
        redis={"url": "redis://redis:6379/0"},
    )


@pytest.mark.asyncio
async def test_ready_reports_both_dependencies_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app(settings=configured_settings(), auth_provider=build_provider())
    database = type("Database", (), {})()
    redis = object()
    app.state.verbaops_runtime_resources = type(
        "RuntimeResources", (), {"database": database, "redis": redis}
    )()
    monkeypatch.setattr(
        "verbaops.api.routes.operations.ping_database", AsyncMock(return_value=True)
    )
    monkeypatch.setattr("verbaops.api.routes.operations.ping_redis", AsyncMock(return_value=True))

    response = await request(app, "GET", "/ready", lifespan=False)

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": [
            {"name": "postgres", "status": "ok"},
            {"name": "redis", "status": "ok"},
        ],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", ["postgres", "redis", "both"])
async def test_ready_returns_safe_503_for_unavailable_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    failed: str,
) -> None:
    app = create_app(settings=configured_settings(), auth_provider=build_provider())
    app.state.verbaops_runtime_resources = type(
        "RuntimeResources", (), {"database": object(), "redis": object()}
    )()
    monkeypatch.setattr(
        "verbaops.api.routes.operations.ping_database",
        AsyncMock(return_value=failed not in {"postgres", "both"}),
    )
    monkeypatch.setattr(
        "verbaops.api.routes.operations.ping_redis",
        AsyncMock(return_value=failed not in {"redis", "both"}),
    )

    response = await request(app, "GET", "/ready", lifespan=False)

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert "secret" not in response.text
    assert "postgresql" not in response.text


@pytest.mark.asyncio
async def test_ready_returns_503_when_resources_are_missing(app: FastAPI) -> None:
    response = await request(app, "GET", "/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": [
            {"name": "postgres", "status": "unavailable"},
            {"name": "redis", "status": "unavailable"},
        ],
    }


@pytest.mark.asyncio
async def test_ready_maps_timed_out_dependency_to_safe_503(monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app(settings=configured_settings(), auth_provider=build_provider())
    app.state.verbaops_runtime_resources = type(
        "RuntimeResources", (), {"database": object(), "redis": object()}
    )()

    async def timed_out(_: object) -> bool:
        raise TimeoutError("secret dependency detail")

    async def healthy(_: object) -> bool:
        return True

    monkeypatch.setattr("verbaops.api.routes.operations.ping_database", timed_out)
    monkeypatch.setattr("verbaops.api.routes.operations.ping_redis", healthy)

    response = await request(app, "GET", "/ready", lifespan=False)

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert "secret dependency detail" not in response.text
