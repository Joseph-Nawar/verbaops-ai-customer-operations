"""Local LiveKit access-token signing behind the narrow customer voice protocol."""

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from livekit import api

from verbaops.config import VoiceSettings


@dataclass(frozen=True, slots=True)
class LiveKitTokenIssuer:
    """Mint only the browser grants required for one server-owned voice room."""

    settings: VoiceSettings

    async def mint_customer_token(
        self,
        *,
        room_identity: str,
        participant_identity: str,
        ttl: timedelta,
    ) -> str:
        """Sign a local JWT; this method performs no LiveKit network operation."""

        _require_opaque_identity(room_identity, prefix="voice-room-")
        _require_opaque_identity(participant_identity, prefix="voice-participant-")
        if ttl <= timedelta(0) or ttl.total_seconds() > self.settings.token_ttl_seconds:
            raise ValueError("LiveKit token TTL is outside the configured bound")

        token = api.AccessToken(
            self.settings.livekit_api_key.get_secret_value(),
            self.settings.livekit_api_secret.get_secret_value(),
        )
        return (
            token.with_identity(participant_identity)
            .with_ttl(ttl)
            .with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=room_identity,
                    can_publish=True,
                    can_subscribe=True,
                    can_publish_data=False,
                    can_publish_sources=["microphone"],
                )
            )
            .to_jwt()
        )


def _require_opaque_identity(value: str, *, prefix: str) -> None:
    """Reject caller-like or non-UUID transport identities before signing."""

    if not value.startswith(prefix):
        raise ValueError("LiveKit identity must be server-generated and opaque")
    try:
        UUID(value.removeprefix(prefix))
    except ValueError:
        raise ValueError("LiveKit identity must be server-generated and opaque") from None
