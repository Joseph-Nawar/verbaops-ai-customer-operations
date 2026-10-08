"""Secret-safe, bounded Stage 7 voice configuration contracts."""

import os
from collections.abc import Callable
from typing import Any, cast

import pytest
from pydantic import SecretStr, ValidationError

from verbaops.config import Settings, VoiceSettings


def make_settings() -> Settings:
    construct = cast(Callable[..., Settings], Settings)
    return construct(_env_file=None)


def clear_verbaops_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in os.environ:
        if key.startswith("VERBAOPS_"):
            monkeypatch.delenv(key, raising=False)


def test_voice_settings_load_nested_values_and_keep_secrets_masked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_verbaops_environment(monkeypatch)
    monkeypatch.setenv("VERBAOPS_VOICE__LIVEKIT_URL", "https://livekit.example.test/")
    monkeypatch.setenv("VERBAOPS_VOICE__LIVEKIT_API_KEY", "livekit-key-sentinel")
    monkeypatch.setenv("VERBAOPS_VOICE__LIVEKIT_API_SECRET", "livekit-secret-sentinel")
    monkeypatch.setenv("VERBAOPS_VOICE__WORKER_TOKEN", "worker-token-sentinel")
    monkeypatch.setenv("VERBAOPS_VOICE__SESSION_TTL_SECONDS", "1800")
    monkeypatch.setenv("VERBAOPS_VOICE__TOKEN_TTL_SECONDS", "300")

    settings = make_settings()

    assert settings.voice.livekit_url == "https://livekit.example.test/"
    assert settings.voice.livekit_api_key == SecretStr("livekit-key-sentinel")
    assert settings.voice.livekit_api_secret == SecretStr("livekit-secret-sentinel")
    assert settings.voice.worker_token == SecretStr("worker-token-sentinel")
    assert settings.voice.session_ttl_seconds == 1800
    assert settings.voice.token_ttl_seconds == 300
    rendered = f"{settings!r} {settings} {settings.voice.model_dump()}"
    assert all(
        secret not in rendered
        for secret in ("livekit-key-sentinel", "livekit-secret-sentinel", "worker-token-sentinel")
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("livekit_api_key", ""),
        ("livekit_api_key", "   "),
        ("livekit_api_secret", ""),
        ("worker_token", " "),
        ("session_ttl_seconds", 0),
        ("session_ttl_seconds", 86401),
        ("token_ttl_seconds", 0),
        ("connection_timeout_seconds", 0),
        ("max_transcript_chars", 4001),
        ("max_turn_seconds", 0),
    ],
)
def test_voice_settings_reject_invalid_or_unbounded_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        VoiceSettings.model_validate(cast(dict[str, Any], {field: value}))


@pytest.mark.parametrize(
    "url",
    [
        "livekit.internal",
        "ftp://livekit.internal",
        "https://user:secret@livekit.internal",
        "https://livekit.internal?secret=sentinel",
        "https://livekit.internal/#secret",
    ],
)
def test_voice_url_rejects_credentials_and_non_http_values_without_echoing_secrets(
    url: str,
) -> None:
    with pytest.raises(ValidationError) as error:
        VoiceSettings(livekit_url=url)

    rendered = (str(error.value), repr(error.value), str(error.value.errors()), error.value.json())
    assert all("secret" not in value and "sentinel" not in value for value in rendered)


def test_voice_settings_reject_extra_fields_and_ttl_inversion() -> None:
    with pytest.raises(ValidationError):
        VoiceSettings.model_validate({"unexpected": "value"})
    with pytest.raises(ValidationError):
        VoiceSettings(session_ttl_seconds=60, token_ttl_seconds=61)


@pytest.mark.parametrize("operation", ["model_copy", "model_construct"])
def test_voice_secret_validation_cannot_be_bypassed(operation: str) -> None:
    settings = VoiceSettings()

    with pytest.raises(ValidationError):
        if operation == "model_copy":
            settings.model_copy(update={"livekit_url": "https://user:secret@livekit.test"})
        else:
            VoiceSettings.model_construct(livekit_url="https://user:secret@livekit.test")
