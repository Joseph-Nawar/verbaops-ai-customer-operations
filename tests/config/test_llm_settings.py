"""Behavioral tests for immutable LLM gateway settings."""

import os
from collections.abc import Callable
from typing import Any, cast

import pytest
from pydantic import SecretStr, ValidationError

from verbaops.config.settings import LLMSettings, Settings


def make_settings() -> Settings:
    """Use BaseSettings' runtime-only _env_file control in tests."""

    construct = cast(Callable[..., Settings], Settings)
    return construct(_env_file=None)


def clear_verbaops_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in os.environ:
        if key.startswith("VERBAOPS_"):
            monkeypatch.delenv(key, raising=False)


def test_nested_environment_variables_load_immutable_llm_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_verbaops_environment(monkeypatch)
    monkeypatch.setenv("VERBAOPS_LLM__BASE_URL", "http://litellm:4000/v1")
    monkeypatch.setenv("VERBAOPS_LLM__API_KEY", "sentinel-api-key")
    monkeypatch.setenv("VERBAOPS_LLM__TIMEOUT_SECONDS", "12.5")

    settings = make_settings()

    assert settings.llm.base_url == "http://litellm:4000/v1"
    assert settings.llm.api_key == SecretStr("sentinel-api-key")
    assert settings.llm.timeout_seconds == 12.5
    assert "sentinel-api-key" not in f"{settings!r} {settings}"

    with pytest.raises(ValidationError):
        settings.llm.timeout_seconds = 20.0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("base_url", "ftp://litellm:4000/v1"),
        ("base_url", "litellm:4000/v1"),
        ("api_key", ""),
        ("api_key", "   "),
        ("timeout_seconds", 0),
        ("timeout_seconds", -1),
    ],
)
def test_llm_settings_reject_invalid_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        LLMSettings.model_validate(cast(dict[str, Any], {field: value}))


def test_llm_settings_reject_extra_fields() -> None:
    with pytest.raises(ValidationError):
        LLMSettings.model_validate({"unexpected": "value"})


@pytest.mark.parametrize(
    "base_url",
    [
        "https://llm-user:llm-secret@litellm:4000/v1",
        "https://llm-secret@litellm:4000/v1",
        "https://:llm-secret@litellm:4000/v1",
        "https://litellm:4000/v1?api_key=llm-secret",
    ],
)
def test_llm_settings_reject_url_credentials_without_echoing_them(base_url: str) -> None:
    with pytest.raises(ValidationError) as error:
        LLMSettings(base_url=base_url)

    rendered = (str(error.value), repr(error.value), str(error.value.errors()), error.value.json())
    assert all("llm-user" not in value and "llm-secret" not in value for value in rendered)


def test_llm_settings_serialization_cannot_contain_url_credentials() -> None:
    settings = LLMSettings(base_url="https://litellm:4000/v1", api_key=SecretStr("api-secret"))

    serialized = f"{settings!r} {settings} {settings.model_dump_json()}"

    assert "api-secret" not in serialized
    assert "@litellm" not in serialized


@pytest.mark.parametrize("operation", ["model_copy", "model_construct"])
def test_llm_settings_cannot_bypass_url_credential_validation(operation: str) -> None:
    settings = LLMSettings()
    credential_url = "https://llm-user:llm-secret@litellm:4000/v1"

    with pytest.raises(ValidationError):
        if operation == "model_copy":
            settings.model_copy(update={"base_url": credential_url})
        else:
            LLMSettings.model_construct(base_url=credential_url)


def test_llm_settings_reject_nested_extra_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_verbaops_environment(monkeypatch)
    monkeypatch.setenv("VERBAOPS_LLM__UNEXPECTED", "value")

    with pytest.raises(ValidationError):
        make_settings()


def test_all_capability_settings_are_runtime_dependencies() -> None:
    import tomllib
    from pathlib import Path

    pyproject = tomllib.loads(
        (Path(__file__).parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert any(
        dependency.startswith("httpx") for dependency in pyproject["project"]["dependencies"]
    )
