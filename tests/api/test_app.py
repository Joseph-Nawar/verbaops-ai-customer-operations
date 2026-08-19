"""Application factory and dependency-container tests."""

import pytest
from fastapi import FastAPI

from relayai.api.app import create_app

from .conftest import build_provider, build_settings, request


def test_application_factory_returns_independent_instances() -> None:
    first_settings = build_settings()
    second_settings = build_settings()
    first_provider = build_provider()
    second_provider = build_provider()

    first = create_app(settings=first_settings, auth_provider=first_provider)
    second = create_app(settings=second_settings, auth_provider=second_provider)

    assert isinstance(first, FastAPI)
    assert isinstance(second, FastAPI)
    assert first is not second
    assert first.state.relayai_dependencies is not second.state.relayai_dependencies
    assert first.state.relayai_dependencies.settings is first_settings
    assert second.state.relayai_dependencies.settings is second_settings
    assert first.state.relayai_dependencies.auth_provider is first_provider
    assert second.state.relayai_dependencies.auth_provider is second_provider


@pytest.mark.asyncio
async def test_application_metadata_uses_package_version(app: FastAPI) -> None:
    response = await request(app, "GET", "/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "RelayAI"
    assert response.json()["info"]["version"] == "0.1.0"
