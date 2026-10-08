"""Provider-free cryptographic and grant-boundary tests for LiveKit tokens."""

import inspect
from datetime import timedelta
from uuid import uuid4

import jwt
import pytest
from pydantic import SecretStr

from verbaops.config import VoiceSettings
from verbaops.voice.livekit import LiveKitTokenIssuer


def _settings() -> VoiceSettings:
    return VoiceSettings(
        livekit_url="wss://livekit.example.test",
        livekit_api_key=SecretStr("test-livekit-key"),
        livekit_api_secret=SecretStr("test-livekit-secret-0123456789012345"),
        worker_token=SecretStr("test-worker-token"),
        token_ttl_seconds=300,
    )


@pytest.mark.asyncio
async def test_customer_token_has_opaque_identity_and_minimum_audio_grants() -> None:
    issuer = LiveKitTokenIssuer(_settings())
    room_identity = f"voice-room-{uuid4()}"
    participant_identity = f"voice-participant-{uuid4()}"

    token = await issuer.mint_customer_token(
        room_identity=room_identity,
        participant_identity=participant_identity,
        ttl=timedelta(seconds=300),
    )
    claims = jwt.decode(
        token,
        _settings().livekit_api_secret.get_secret_value(),
        algorithms=["HS256"],
        issuer=_settings().livekit_api_key.get_secret_value(),
    )
    video = claims["video"]
    assert claims["sub"] == participant_identity
    assert video["room"] == room_identity
    assert video["roomJoin"] is True
    assert video["canPublish"] is True
    assert video["canSubscribe"] is True
    assert video["canPublishData"] is False
    assert video["canPublishSources"] == ["microphone"]
    assert "roomAdmin" not in video
    assert "roomCreate" not in video
    assert "roomRecord" not in video
    assert "ingressAdmin" not in video
    assert "recorder" not in video
    assert "agent" not in video
    assert "sip" not in claims
    assert "attributes" not in claims
    assert "metadata" not in claims
    decoded = jwt.decode(token, options={"verify_signature": False})
    assert decoded["exp"] - decoded["nbf"] <= 300


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("room_identity", "participant_identity"),
    [("customer@example.com", "voice-participant-id"), ("voice-room-id", "customer@example.com")],
)
async def test_issuer_rejects_non_opaque_transport_identities(
    room_identity: str,
    participant_identity: str,
) -> None:
    issuer = LiveKitTokenIssuer(_settings())

    with pytest.raises(ValueError):
        await issuer.mint_customer_token(
            room_identity=room_identity,
            participant_identity=participant_identity,
            ttl=timedelta(seconds=300),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("ttl", [timedelta(0), timedelta(seconds=301), timedelta(hours=1)])
async def test_issuer_rejects_zero_or_overridden_ttl(ttl: timedelta) -> None:
    issuer = LiveKitTokenIssuer(_settings())

    with pytest.raises(ValueError):
        await issuer.mint_customer_token(
            room_identity=f"voice-room-{uuid4()}",
            participant_identity=f"voice-participant-{uuid4()}",
            ttl=ttl,
        )


def test_issuer_has_no_role_or_grant_override_inputs_and_hides_secrets() -> None:
    signature = inspect.signature(LiveKitTokenIssuer.mint_customer_token)
    assert set(signature.parameters) == {"self", "room_identity", "participant_identity", "ttl"}
    issuer = LiveKitTokenIssuer(_settings())
    rendered = f"{issuer!r} {issuer}"
    assert "test-livekit-key" not in rendered
    assert "test-livekit-secret" not in rendered
