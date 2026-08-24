"""Tests for the Uvicorn composition root."""

import pytest

from verbaops.api.runtime import RuntimeConfigurationError, create_runtime_app
from verbaops.config.settings import Environment


def test_runtime_factory_builds_a_server_mapped_development_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VERBAOPS_ENVIRONMENT", Environment.DEVELOPMENT.value)
    monkeypatch.delenv("VERBAOPS_DATABASE__URL", raising=False)
    monkeypatch.delenv("VERBAOPS_REDIS__URL", raising=False)

    app = create_runtime_app()

    provider = app.state.verbaops_dependencies.auth_provider
    context = provider.authenticate(next(iter(provider._contexts)))
    assert context.roles == {"customer"}
    assert (
        context.customer_id == app.state.verbaops_dependencies.settings.auth.development_customer_id
    )


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
