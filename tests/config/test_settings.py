"""Behavioral tests for validated VerbaOps AI settings."""

import os
from collections.abc import Callable
from typing import cast

import pytest
from pydantic import ValidationError

from verbaops.config.settings import Environment, LogLevel, Settings


def make_settings() -> Settings:
    """Use BaseSettings' runtime-only _env_file control without weakening production typing."""

    construct = cast(Callable[..., Settings], Settings)
    return construct(_env_file=None)


def clear_verbaops_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in os.environ:
        if key.startswith("VERBAOPS_"):
            monkeypatch.delenv(key, raising=False)


def test_default_development_configuration_is_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_verbaops_environment(monkeypatch)

    settings = make_settings()

    assert settings.environment is Environment.DEVELOPMENT
    assert settings.database.url is None
    assert settings.redis.url is None
    assert settings.observability.log_level is LogLevel.INFO


def test_prefixed_nested_environment_variables_load(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_verbaops_environment(monkeypatch)
    monkeypatch.setenv("VERBAOPS_ENVIRONMENT", "development")
    monkeypatch.setenv("VERBAOPS_DATABASE__URL", "postgresql://user:db-secret@db/app")
    monkeypatch.setenv("VERBAOPS_REDIS__URL", "redis://:redis-secret@cache/0")
    monkeypatch.setenv("VERBAOPS_OBSERVABILITY__LOG_LEVEL", "DEBUG")

    settings = make_settings()

    assert settings.database.url is not None
    assert settings.database.url.get_secret_value() == "postgresql://user:db-secret@db/app"
    assert settings.redis.url is not None
    assert settings.redis.url.get_secret_value() == "redis://:redis-secret@cache/0"
    assert settings.observability.log_level is LogLevel.DEBUG


def test_old_environment_prefix_is_not_authoritative(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_verbaops_environment(monkeypatch)
    monkeypatch.setenv("RELAYAI_ENVIRONMENT", "production")
    monkeypatch.setenv("RELAYAI_DATABASE__URL", "postgresql://old-user:old-secret@db/app")
    monkeypatch.setenv("RELAYAI_REDIS__URL", "redis://:old-secret@cache/0")

    settings = make_settings()

    assert settings.environment is Environment.DEVELOPMENT
    assert settings.database.url is None
    assert settings.redis.url is None


def test_invalid_environment_value_fails_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_verbaops_environment(monkeypatch)
    monkeypatch.setenv("VERBAOPS_ENVIRONMENT", "invalid")

    with pytest.raises(ValidationError):
        make_settings()


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_deployed_environment_requires_database_and_redis(
    monkeypatch: pytest.MonkeyPatch,
    environment: str,
) -> None:
    clear_verbaops_environment(monkeypatch)
    monkeypatch.setenv("VERBAOPS_ENVIRONMENT", environment)

    with pytest.raises(ValidationError):
        make_settings()


@pytest.mark.parametrize("environment", ["staging", "production"])
@pytest.mark.parametrize("field", ["VERBAOPS_DATABASE__URL", "VERBAOPS_REDIS__URL"])
@pytest.mark.parametrize("value", ["", "   "])
def test_deployed_environment_rejects_blank_infrastructure_urls(
    monkeypatch: pytest.MonkeyPatch,
    environment: str,
    field: str,
    value: str,
) -> None:
    clear_verbaops_environment(monkeypatch)
    monkeypatch.setenv("VERBAOPS_ENVIRONMENT", environment)
    monkeypatch.setenv(field, value)
    if field == "VERBAOPS_DATABASE__URL":
        monkeypatch.setenv("VERBAOPS_REDIS__URL", "redis://:valid@cache/0")
    else:
        monkeypatch.setenv("VERBAOPS_DATABASE__URL", "postgresql://valid@db/app")

    with pytest.raises(ValidationError):
        make_settings()


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_deployed_environment_with_database_and_redis_is_valid(
    monkeypatch: pytest.MonkeyPatch,
    environment: str,
) -> None:
    clear_verbaops_environment(monkeypatch)
    monkeypatch.setenv("VERBAOPS_ENVIRONMENT", environment)
    monkeypatch.setenv("VERBAOPS_DATABASE__URL", "postgresql://user:secret@db/app")
    monkeypatch.setenv("VERBAOPS_REDIS__URL", "redis://:secret@cache/0")

    settings = make_settings()

    assert settings.environment.value == environment
    assert settings.database.url is not None
    assert settings.redis.url is not None


def test_secret_values_are_masked_in_normal_representations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_verbaops_environment(monkeypatch)
    monkeypatch.setenv("VERBAOPS_DATABASE__URL", "postgresql://user:db-secret@db/app")
    monkeypatch.setenv("VERBAOPS_REDIS__URL", "redis://:redis-secret@cache/0")

    settings = make_settings()
    representation = f"{settings!r} {settings}"

    assert "db-secret" not in representation
    assert "redis-secret" not in representation


def test_settings_are_immutable(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_verbaops_environment(monkeypatch)
    settings = make_settings()

    with pytest.raises(ValidationError):
        settings.environment = Environment.TEST

    with pytest.raises(ValidationError):
        settings.observability.log_level = LogLevel.DEBUG


def test_unsupported_nested_settings_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_verbaops_environment(monkeypatch)
    monkeypatch.setenv("VERBAOPS_DATABASE__MISPELLED", "unexpected")

    with pytest.raises(ValidationError):
        make_settings()


def test_settings_instances_do_not_share_environment_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_verbaops_environment(monkeypatch)
    monkeypatch.setenv("VERBAOPS_DATABASE__URL", "postgresql://user:first@db/app")
    first = make_settings()

    monkeypatch.delenv("VERBAOPS_DATABASE__URL")
    second = make_settings()

    assert first.database.url is not None
    assert first.database.url.get_secret_value() == "postgresql://user:first@db/app"
    assert second.database.url is None
