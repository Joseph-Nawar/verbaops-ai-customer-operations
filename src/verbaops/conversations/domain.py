"""Application-owned conversation and trace records."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from verbaops.llm.models import ResponseMetadata


@dataclass(frozen=True, slots=True)
class ConversationScope:
    """Trusted tenant and principal scope required for every conversation read."""

    tenant_id: UUID
    principal_id: UUID


@dataclass(frozen=True, slots=True)
class ConversationRecord:
    id: UUID
    tenant_id: UUID
    principal_id: UUID
    customer_id: UUID | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MessageRecord:
    id: UUID
    conversation_id: UUID
    sequence: int
    role: str
    content: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class MessagePage:
    """One bounded, chronological page of customer-visible messages."""

    messages: tuple[MessageRecord, ...]
    has_more: bool
    next_before_sequence: int | None


@dataclass(frozen=True, slots=True)
class AgentRunRecord:
    id: UUID
    conversation_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID | None
    status: str
    graph_version: str
    prompt_version: str
    tool_schema_version: str
    started_at: datetime
    completed_at: datetime | None
    error_code: str | None


@dataclass(frozen=True, slots=True)
class ModelCallRecord:
    id: UUID
    agent_run_id: UUID
    sequence: int
    capability_alias: str
    gateway_request_id: str | None
    gateway_model_id: str | None
    model: str | None
    provider: str | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    latency_ms: float | None
    cost_usd: float | None
    finish_reason: str | None
    status: str
    error_code: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ToolInvocationRecord:
    id: UUID
    agent_run_id: UUID
    sequence: int
    tool_call_id: str
    tool_name: str
    risk_level: str
    arguments_json: dict[str, Any]
    result_json: Any | None
    status: str
    latency_ms: float | None
    error_code: str | None
    created_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class TurnStart:
    conversation: ConversationRecord
    user_message: MessageRecord
    agent_run: AgentRunRecord


@dataclass(frozen=True, slots=True)
class TurnCompletion:
    assistant_message: MessageRecord
    agent_run: AgentRunRecord


def model_call_fields(metadata: ResponseMetadata) -> dict[str, Any]:
    """Convert the M3A metadata contract to persistence fields without inference."""

    if metadata.capability_alias is None:
        raise ValueError("model call capability_alias is required")
    return {
        "capability_alias": metadata.capability_alias.value,
        "gateway_request_id": metadata.gateway_request_id,
        "gateway_model_id": metadata.gateway_model_id,
        "model": metadata.model,
        "provider": metadata.provider,
        "input_tokens": metadata.input_tokens,
        "output_tokens": metadata.output_tokens,
        "total_tokens": metadata.total_tokens,
        "latency_ms": metadata.latency_ms,
        "cost_usd": metadata.cost_usd,
        "finish_reason": metadata.finish_reason,
    }
