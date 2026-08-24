"""Behavioral tests for immutable VerbaOps Commerce settings."""

import os
from collections.abc import Callable
from types import MappingProxyType
from typing import Any, cast

import pytest
from pydantic import SecretStr, ValidationError

from verbaops.config import CommerceSettings, Settings


def make_settings() -> Settings:
    """Use BaseSettings' runtime-only _env_file control in tests."""

    construct = cast(Callable[..., Settings], Settings)
    return construct(_env_file=None)


def clear_verbaops_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in os.environ:
        if key.startswith("VERBAOPS_"):
            monkeypatch.delenv(key, raising=False)


def test_nested_environment_variables_load_immutable_commerce_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_verbaops_environment(monkeypatch)
    monkeypatch.setenv("VERBAOPS_COMMERCE__BASE_URL", "https://commerce.internal/v1/")
    monkeypatch.setenv("VERBAOPS_COMMERCE__SERVICE_TOKEN", "sentinel-commerce-token")
    monkeypatch.setenv("VERBAOPS_COMMERCE__TIMEOUT_SECONDS", "12.5")

    settings = make_settings()

    assert settings.commerce.base_url == "https://commerce.internal/v1/"
    assert settings.commerce.service_token == SecretStr("sentinel-commerce-token")
    assert settings.commerce.timeout_seconds == 12.5
    assert "sentinel-commerce-token" not in f"{settings!r} {settings}"

    with pytest.raises(ValidationError):
        settings.commerce.timeout_seconds = 20.0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("base_url", "ftp://commerce.internal"),
        ("base_url", "commerce.internal"),
        ("service_token", ""),
        ("service_token", "   "),
        ("timeout_seconds", 0),
        ("timeout_seconds", -1),
    ],
)
def test_commerce_settings_reject_invalid_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        CommerceSettings.model_validate(cast(dict[str, Any], {field: value}))


def test_commerce_settings_reject_extra_fields() -> None:
    with pytest.raises(ValidationError):
        CommerceSettings.model_validate({"unexpected": "value"})


@pytest.mark.parametrize(
    "base_url",
    [
        "https://commerce-user:commerce-secret@commerce.internal",
        "https://commerce-secret@commerce.internal",
        "https://:commerce-secret@commerce.internal",
        "https://commerce.internal?token=commerce-secret",
        "https://[#commerce-secret",
    ],
)
def test_commerce_settings_reject_url_secrets_without_echoing_them(base_url: str) -> None:
    with pytest.raises(ValidationError) as error:
        CommerceSettings(base_url=base_url)

    rendered = (str(error.value), repr(error.value), str(error.value.errors()), error.value.json())
    assert all(
        "commerce-user" not in value and "commerce-secret" not in value for value in rendered
    )


def test_commerce_settings_sanitize_mapping_proxy_before_validation() -> None:
    with pytest.raises(ValidationError) as error:
        CommerceSettings.model_validate(
            MappingProxyType(
                {"base_url": "https://commerce-user:commerce-secret@commerce.internal"}
            )
        )

    rendered = (str(error.value), repr(error.value), str(error.value.errors()), error.value.json())
    assert all(
        "commerce-user" not in value and "commerce-secret" not in value for value in rendered
    )


@pytest.mark.parametrize("operation", ["model_copy", "model_construct"])
def test_commerce_settings_cannot_bypass_url_secret_validation(operation: str) -> None:
    settings = CommerceSettings()
    credential_url = "https://commerce-user:commerce-secret@commerce.internal"

    with pytest.raises(ValidationError):
        if operation == "model_copy":
            settings.model_copy(update={"base_url": credential_url})
        else:
            CommerceSettings.model_construct(base_url=credential_url)
