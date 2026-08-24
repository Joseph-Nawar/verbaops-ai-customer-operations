"""Authenticated, customer-visible conversation HTTP routes."""

from datetime import datetime
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from verbaops.agent.errors import (
    AgentBudgetExceededError,
    AgentBusyError,
    AgentError,
    AgentInputError,
    AgentProtocolError,
    AgentUnavailableError,
)
from verbaops.agent.runtime import AgentRuntime, AgentTurnResult
from verbaops.api.dependencies import (
    get_agent_runtime,
    get_conversation_service,
    get_trusted_context,
)
from verbaops.api.errors import PublicAPIError
from verbaops.auth.context import TrustedContext
from verbaops.conversations.domain import (
    ConversationRecord,
    ConversationScope,
    MessagePage,
    MessageRecord,
)
from verbaops.conversations.errors import ConversationBusyError, ConversationNotFoundError
from verbaops.conversations.service import ConversationService

router = APIRouter(prefix="/v1/conversations", tags=["conversations"])


class CreateConversationRequest(BaseModel):
    """Intentionally empty request body for conversation creation."""

    model_config = ConfigDict(extra="forbid")


class SendMessageRequest(BaseModel):
    """Strict customer message input."""

    model_config = ConfigDict(extra="forbid")

    content: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000)]


class PublicMessage(BaseModel):
    id: UUID
    conversation_id: UUID
    sequence: int = Field(gt=0)
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class ConversationCreatedResponse(BaseModel):
    conversation_id: UUID
    created_at: datetime
    updated_at: datetime


class MessageResponse(BaseModel):
    conversation_id: UUID
    run_id: UUID
    user_message: PublicMessage
    assistant_message: PublicMessage


class ConversationResponse(BaseModel):
    conversation_id: UUID
    created_at: datetime
    updated_at: datetime
    messages: list[PublicMessage]
    has_more: bool
    next_before_sequence: int | None


ContextDependency = Annotated[TrustedContext, Depends(get_trusted_context)]
ServiceDependency = Annotated[ConversationService, Depends(get_conversation_service)]
RuntimeDependency = Annotated[AgentRuntime, Depends(get_agent_runtime)]


@router.post("", response_model=ConversationCreatedResponse, status_code=201)
async def create_conversation(
    _request: CreateConversationRequest,
    context: ContextDependency,
    service: ServiceDependency,
) -> ConversationCreatedResponse:
    if context.customer_id is None:
        raise PublicAPIError(403, "customer_context_required", "customer context is required")
    record = await service.create_conversation(_scope(context), context.customer_id)
    return ConversationCreatedResponse(
        conversation_id=record.id,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.post("/{conversation_id}/messages", response_model=MessageResponse)
async def send_message(
    conversation_id: UUID,
    request: SendMessageRequest,
    context: ContextDependency,
    runtime: RuntimeDependency,
) -> MessageResponse:
    if context.customer_id is None:
        raise PublicAPIError(403, "customer_context_required", "customer context is required")
    try:
        result = await runtime.run_turn(
            _scope(context), conversation_id, context.customer_id, request.content
        )
    except ConversationNotFoundError:
        raise PublicAPIError(404, "conversation_not_found", "conversation not found") from None
    except (ConversationBusyError, AgentBusyError):
        raise PublicAPIError(409, "conversation_busy", "conversation is busy") from None
    except AgentUnavailableError:
        raise PublicAPIError(503, "agent_unavailable", "agent is unavailable") from None
    except (AgentProtocolError, AgentBudgetExceededError):
        raise PublicAPIError(502, "agent_execution_failed", "agent execution failed") from None
    except AgentInputError:
        raise PublicAPIError(422, "request_validation_error", "request validation failed") from None
    except AgentError:
        raise PublicAPIError(502, "agent_execution_failed", "agent execution failed") from None
    return _message_response(result)


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: UUID,
    context: ContextDependency,
    service: ServiceDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    before_sequence: Annotated[int | None, Query(gt=0)] = None,
) -> ConversationResponse:
    try:
        record = await service.get_conversation(_scope(context), conversation_id)
        page = await service.list_messages_page(
            _scope(context), conversation_id, limit=limit, before_sequence=before_sequence
        )
    except ConversationNotFoundError:
        raise PublicAPIError(404, "conversation_not_found", "conversation not found") from None
    return _conversation_response(record, page)


def _scope(context: TrustedContext) -> ConversationScope:
    return ConversationScope(tenant_id=context.tenant_id, principal_id=context.principal_id)


def _public_message(record: MessageRecord) -> PublicMessage:
    return PublicMessage(
        id=record.id,
        conversation_id=record.conversation_id,
        sequence=record.sequence,
        role=cast(Literal["user", "assistant"], record.role),
        content=record.content,
        created_at=record.created_at,
    )


def _message_response(result: AgentTurnResult) -> MessageResponse:
    return MessageResponse(
        conversation_id=result.conversation_id,
        run_id=result.agent_run_id,
        user_message=_public_message(result.user_message),
        assistant_message=_public_message(result.assistant_message),
    )


def _conversation_response(record: ConversationRecord, page: MessagePage) -> ConversationResponse:
    return ConversationResponse(
        conversation_id=record.id,
        created_at=record.created_at,
        updated_at=record.updated_at,
        messages=[_public_message(message) for message in page.messages],
        has_more=page.has_more,
        next_before_sequence=page.next_before_sequence,
    )
