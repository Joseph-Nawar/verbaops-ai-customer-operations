"""Tests for the Uvicorn composition root."""

import pytest

from verbaops.api.runtime import RuntimeConfigurationError, create_runtime_app
from verbaops.config.settings import Environment


def test_runtime_factory_uses_empty_development_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERBAOPS_ENVIRONMENT", Environment.DEVELOPMENT.value)
    monkeypatch.delenv("VERBAOPS_DATABASE__URL", raising=False)
    monkeypatch.delenv("VERBAOPS_REDIS__URL", raising=False)

    app = create_runtime_app()

    assert app.state.verbaops_dependencies.auth_provider._contexts == {}


@pytest.mark.parametrize("environment", [Environment.STAGING, Environment.PRODUCTION])
def test_runtime_factory_fails_closed_before_production_identity_provider(
    monkeypatch: pytest.MonkeyPatch,
    environment: Environment,
) -> None:
    monkeypatch.setenv("VERBAOPS_ENVIRONMENT", environment.value)
    monkeypatch.setenv("VERBAOPS_DATABASE__URL", "postgresql+asyncpg://verbaops:secret@db/app")
    monkeypatch.setenv("VERBAOPS_REDIS__URL", "redis://redis:6379/0")

    with pytest.raises(RuntimeConfigurationError):
        create_runtime_app()
