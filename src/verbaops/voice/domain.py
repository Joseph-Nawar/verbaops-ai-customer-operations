"""Server-owned voice session domain records and bounded lifecycle values."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class VoiceSessionState(StrEnum):
    """The closed lifecycle of one browser voice transport session."""

    CREATED = "created"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ENDED = "ended"


@dataclass(frozen=True, slots=True)
class VoiceSessionRecord:
    """Durable, bounded session state; no credentials or authorization claims."""

    id: UUID
    tenant_id: UUID
    principal_id: UUID
    customer_id: UUID
    conversation_id: UUID
    transport_provider: str
    stt_provider: str
    tts_provider: str
    room_identity: str
    participant_identity: str
    status: VoiceSessionState
    created_at: datetime
    connected_at: datetime | None
    ended_at: datetime | None
    error_code: str | None
