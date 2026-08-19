"""Tests for the Uvicorn composition root."""

import pytest

from relayai.api.runtime import RuntimeConfigurationError, create_runtime_app
from relayai.config.settings import Environment


def test_runtime_factory_uses_empty_development_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RELAYAI_ENVIRONMENT", Environment.DEVELOPMENT.value)
    monkeypatch.delenv("RELAYAI_DATABASE__URL", raising=False)
    monkeypatch.delenv("RELAYAI_REDIS__URL", raising=False)

    app = create_runtime_app()

    assert app.state.relayai_dependencies.auth_provider._contexts == {}


@pytest.mark.parametrize("environment", [Environment.STAGING, Environment.PRODUCTION])
def test_runtime_factory_fails_closed_before_production_identity_provider(
    monkeypatch: pytest.MonkeyPatch,
    environment: Environment,
) -> None:
    monkeypatch.setenv("RELAYAI_ENVIRONMENT", environment.value)
    monkeypatch.setenv("RELAYAI_DATABASE__URL", "postgresql+asyncpg://relayai:secret@db/app")
    monkeypatch.setenv("RELAYAI_REDIS__URL", "redis://redis:6379/0")

    with pytest.raises(RuntimeConfigurationError):
        create_runtime_app()
