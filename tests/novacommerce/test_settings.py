"""NovaCommerce settings contract tests."""

import os
from collections.abc import Callable
from typing import cast

import pytest
from pydantic import ValidationError

from novacommerce.config.settings import Environment, LogLevel, Settings


def make_settings() -> Settings:
    construct = cast(Callable[..., Settings], Settings)
    return construct(_env_file=None)


def clear_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in os.environ:
        if key.startswith("NOVACOMMERCE_"):
            monkeypatch.delenv(key, raising=False)


def test_default_settings_are_development_without_database(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_environment(monkeypatch)
    settings = make_settings()
    assert settings.environment is Environment.DEVELOPMENT
    assert settings.database.url is None
    assert settings.observability.log_level is LogLevel.INFO


def test_nested_prefixed_environment_variables_load_as_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_environment(monkeypatch)
    monkeypatch.setenv("NOVACOMMERCE_ENVIRONMENT", "test")
    monkeypatch.setenv("NOVACOMMERCE_DATABASE__URL", "postgresql+asyncpg://user:secret@db/commerce")
    monkeypatch.setenv("NOVACOMMERCE_OBSERVABILITY__LOG_LEVEL", "DEBUG")
    settings = make_settings()
    assert settings.database.url is not None
    assert settings.database.url.get_secret_value().endswith("/commerce")
    assert settings.observability.log_level is LogLevel.DEBUG


@pytest.mark.parametrize("environment", ["staging", "production"])
@pytest.mark.parametrize("value", [None, "", "   "])
def test_deployed_environments_require_non_blank_database_url(
    monkeypatch: pytest.MonkeyPatch,
    environment: str,
    value: str | None,
) -> None:
    clear_environment(monkeypatch)
    monkeypatch.setenv("NOVACOMMERCE_ENVIRONMENT", environment)
    if value is not None:
        monkeypatch.setenv("NOVACOMMERCE_DATABASE__URL", value)
    with pytest.raises(ValidationError):
        make_settings()


def test_extra_configuration_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_environment(monkeypatch)
    monkeypatch.setenv("NOVACOMMERCE_DATABASE__UNKNOWN", "nope")
    with pytest.raises(ValidationError):
        make_settings()


def test_settings_are_immutable(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_environment(monkeypatch)
    settings = make_settings()
    with pytest.raises(ValidationError):
        settings.environment = Environment.TEST
