"""Strict internal Voice Worker final-transcript boundary."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from verbaops.agent.errors import (
    AgentBusyError,
    AgentInputError,
    AgentUnavailableError,
    AgentVoiceTurnFailedError,
    AgentVoiceTurnInProgressError,
)
from verbaops.agent.runtime import AgentRuntime
from verbaops.api.dependencies import (
    get_agent_runtime,
    get_voice_session_service,
    get_voice_worker_context,
)
from verbaops.api.errors import PublicAPIError
from verbaops.conversations.domain import InteractionMode
from verbaops.voice.auth import VoiceWorkerContext
from verbaops.voice.errors import (
    VoiceSessionExpiredError,
    VoiceSessionLifecycleError,
    VoiceSessionNotFoundError,
)
from verbaops.voice.models import VoiceFinalTranscriptRequest, VoiceTurnResult
from verbaops.voice.results import to_voice_turn_result
from verbaops.voice.service import VoiceSessionService, delegated_customer_context

router = APIRouter(prefix="/internal/voice/sessions", tags=["voice-internal"])

WorkerDependency = Annotated[VoiceWorkerContext, Depends(get_voice_worker_context)]
SessionServiceDependency = Annotated[VoiceSessionService, Depends(get_voice_session_service)]
RuntimeDependency = Annotated[AgentRuntime, Depends(get_agent_runtime)]


@router.post("/{voice_session_id}/final-transcripts", response_model=VoiceTurnResult)
async def submit_final_transcript(
    voice_session_id: UUID,
    request: VoiceFinalTranscriptRequest,
    worker_context: WorkerDependency,
    service: SessionServiceDependency,
    runtime: RuntimeDependency,
) -> VoiceTurnResult:
    """Submit one explicit FINAL event using only server-owned session identity."""

    try:
        session = await service.get_connected_worker_session(voice_session_id, worker_context)
    except VoiceSessionNotFoundError:
        raise PublicAPIError(404, "voice_session_not_found", "voice session not found") from None
    except VoiceSessionExpiredError:
        raise PublicAPIError(404, "voice_session_not_found", "voice session not found") from None
    except VoiceSessionLifecycleError:
        raise PublicAPIError(
            409, "voice_session_unavailable", "voice session unavailable"
        ) from None

    trusted_context = delegated_customer_context(session)
    try:
        result = await runtime.run_turn(
            trusted_context,
            session.conversation_id,
            request.transcript,
            interaction_mode=InteractionMode.VOICE,
            voice_session_id=session.id,
            voice_turn_id=request.voice_turn_id,
        )
    except AgentVoiceTurnInProgressError:
        raise PublicAPIError(
            409, "voice_turn_in_progress", "voice turn is already in progress"
        ) from None
    except AgentVoiceTurnFailedError:
        raise PublicAPIError(502, "voice_turn_failed", "voice turn previously failed") from None
    except AgentBusyError:
        raise PublicAPIError(409, "voice_turn_busy", "conversation is busy") from None
    except AgentInputError:
        raise PublicAPIError(422, "voice_turn_invalid", "voice turn is invalid") from None
    except AgentUnavailableError:
        raise PublicAPIError(503, "voice_turn_unavailable", "voice turn unavailable") from None

    return to_voice_turn_result(
        result,
        voice_session_id=session.id,
        voice_turn_id=request.voice_turn_id,
    )
