"""Customer-only browser voice bootstrap and terminal end routes."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from verbaops.api.dependencies import get_trusted_context, get_voice_session_service
from verbaops.api.errors import PublicAPIError
from verbaops.auth.context import TrustedContext
from verbaops.voice.domain import VoiceSessionState
from verbaops.voice.errors import (
    VoiceSessionAuthorizationError,
    VoiceSessionError,
    VoiceSessionExpiredError,
    VoiceSessionLifecycleError,
    VoiceSessionNotFoundError,
)
from verbaops.voice.models import VoiceSessionBootstrap, VoiceSessionCreateRequest
from verbaops.voice.service import VoiceSessionService

router = APIRouter(prefix="/v1/voice/sessions", tags=["voice"])

ContextDependency = Annotated[TrustedContext, Depends(get_trusted_context)]
ServiceDependency = Annotated[VoiceSessionService, Depends(get_voice_session_service)]


class VoiceSessionEndResponse(BaseModel):
    """Bounded transport lifecycle response; it never contains action state."""

    model_config = ConfigDict(extra="forbid")

    voice_session_id: UUID
    status: VoiceSessionState
    ended_at: datetime


@router.post("", response_model=VoiceSessionBootstrap, status_code=201)
async def create_voice_session(
    request: VoiceSessionCreateRequest,
    context: ContextDependency,
    service: ServiceDependency,
) -> VoiceSessionBootstrap:
    """Create one server-owned customer voice capability."""

    try:
        return await service.create_customer_session(context, request.conversation_id)
    except VoiceSessionAuthorizationError:
        raise PublicAPIError(
            403, "customer_context_required", "customer context is required"
        ) from None
    except (VoiceSessionNotFoundError, VoiceSessionExpiredError):
        raise PublicAPIError(404, "voice_session_not_found", "voice session not found") from None
    except VoiceSessionError:
        raise PublicAPIError(
            409, "voice_session_unavailable", "voice session unavailable"
        ) from None


@router.post("/{voice_session_id}/end", response_model=VoiceSessionEndResponse)
async def end_voice_session(
    voice_session_id: UUID,
    request: Request,
    context: ContextDependency,
    service: ServiceDependency,
) -> VoiceSessionEndResponse:
    """End a customer-owned session without changing Stage 6 business state."""

    if (await request.body()).strip():
        raise PublicAPIError(422, "request_validation_error", "request validation failed")
    try:
        record = await service.end_customer_session(voice_session_id, context)
    except VoiceSessionAuthorizationError:
        raise PublicAPIError(
            403, "customer_context_required", "customer context is required"
        ) from None
    except VoiceSessionNotFoundError:
        raise PublicAPIError(404, "voice_session_not_found", "voice session not found") from None
    except VoiceSessionLifecycleError:
        raise PublicAPIError(
            409, "voice_session_unavailable", "voice session unavailable"
        ) from None
    if record.ended_at is None:
        raise PublicAPIError(500, "internal_error", "internal server error")
    return VoiceSessionEndResponse(
        voice_session_id=record.id,
        status=record.status,
        ended_at=record.ended_at,
    )
