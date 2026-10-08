"""Strict public and internal voice DTOs without caller-supplied identity."""

from datetime import datetime
from typing import Annotated, ClassVar
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, StringConstraints

from verbaops.voice.domain import VoiceSessionState


class VoiceSessionCreateRequest(BaseModel):
    """The only optional browser bootstrap input."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    conversation_id: UUID | None = None


class VoiceSessionBootstrap(BaseModel):
    """Exact customer-facing bootstrap response; identities stay server-owned."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    voice_session_id: UUID
    conversation_id: UUID
    livekit_url: AnyHttpUrl
    room_token: str
    token_expires_at: datetime
    status: VoiceSessionState


class VoiceFinalTranscriptRequest(BaseModel):
    """Frozen M7B request shape, defined now only as a strict shared DTO."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", strict=True)

    voice_turn_id: UUID
    transcript: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
    ]
