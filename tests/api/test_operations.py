"""Operational endpoint and OpenAPI tests."""

import pytest
from fastapi import FastAPI

from .conftest import request


@pytest.mark.asyncio
async def test_health_is_liveness_only(app: FastAPI) -> None:
    response = await request(app, "GET", "/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_ready_reports_no_external_checks_yet(app: FastAPI) -> None:
    response = await request(app, "GET", "/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": []}


@pytest.mark.asyncio
async def test_version_reports_service_version_and_environment(app: FastAPI) -> None:
    response = await request(app, "GET", "/version")

    assert response.status_code == 200
    assert response.json() == {
        "service": "relayai",
        "version": "0.1.0",
        "environment": "development",
    }


@pytest.mark.asyncio
async def test_openapi_contains_operational_routes(app: FastAPI) -> None:
    response = await request(app, "GET", "/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert {"/health", "/ready", "/version"}.issubset(paths)
