"""Strict public and internal voice DTOs without caller-supplied identity."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, ClassVar, Literal
from uuid import UUID

from pydantic import AnyWebsocketUrl, BaseModel, ConfigDict, StringConstraints

from verbaops.actions.models import ActionRequestSummary, ActionState, ActionType
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
    livekit_url: AnyWebsocketUrl
    room_token: str
    token_expires_at: datetime
    status: VoiceSessionState


class VoiceFinalTranscriptRequest(BaseModel):
    """The complete internal worker request; identity is never caller supplied."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    voice_turn_id: UUID
    transcript: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
    ]


class VoiceTurnOutcome(StrEnum):
    """Bounded worker presentation outcome derived from durable server state."""

    NORMAL_ANSWER = "normal_answer"
    ACTION_PENDING = "action_pending"
    AWAITING_APPROVAL = "awaiting_approval"
    ACTION_RESULT = "action_result"
    FAILURE = "failure"


class VoiceActionPrompt(BaseModel):
    """Structured action information reserved for the later confirmation milestone."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    action_request_id: UUID
    action_type: ActionType
    state: ActionState
    proposal_fingerprint: str
    spoken_summary: str
    required_next_actor: Literal["customer", "support_supervisor", "none"]
    permitted_operations: tuple[Literal["confirm", "reject"], ...]


class VoiceTurnResult(BaseModel):
    """Server-owned structured result consumed by the provider-neutral worker."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    voice_session_id: UUID
    conversation_id: UUID
    voice_turn_id: UUID
    agent_run_id: UUID
    assistant_message_id: UUID
    assistant_text: str
    outcome: VoiceTurnOutcome
    action_requests: tuple[ActionRequestSummary, ...]
    action_prompt: VoiceActionPrompt | None
