"""Immutable, application-owned LLM request and response models."""

import json
from enum import StrEnum
from typing import Any, Literal, TypeVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_serializer


class CapabilityAlias(StrEnum):
    """Stable capability names mapped by the gateway to provider models."""

    AGENT_FAST = "agent-fast"
    AGENT_REASONING = "agent-reasoning"
    EVAL_JUDGE = "eval-judge"
    EMBEDDING_MULTILINGUAL = "embedding-multilingual"


class ToolCall(BaseModel):
    """A normalized function call returned by an LLM."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str
    arguments: dict[str, Any]

    def as_openai(self) -> dict[str, Any]:
        """Return the OpenAI chat-completions representation of this call."""

        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False, separators=(",", ":")),
            },
        }


class ChatMessage(BaseModel):
    """A provider-independent chat message with optional function calls."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: tuple[ToolCall, ...] | None = None

    @model_serializer(mode="plain")
    def serialize_openai(self) -> dict[str, Any]:
        """Serialize messages using the OpenAI chat-completions shape."""

        message: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name is not None:
            message["name"] = self.name
        if self.tool_call_id is not None:
            message["tool_call_id"] = self.tool_call_id
        if self.tool_calls is not None:
            message["tool_calls"] = [tool_call.as_openai() for tool_call in self.tool_calls]
        return message


class ToolDefinition(BaseModel):
    """An application-owned function schema accepted by an LLM request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    description: str | None = None
    parameters: dict[str, Any]

    @model_serializer(mode="plain")
    def serialize_openai(self) -> dict[str, Any]:
        """Serialize a tool as an OpenAI function definition."""

        function: dict[str, Any] = {"name": self.name, "parameters": self.parameters}
        if self.description is not None:
            function["description"] = self.description
        return {"type": "function", "function": function}


class GenerateRequest(BaseModel):
    """OpenAI-compatible generation input owned by VerbaOps."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    capability: CapabilityAlias = Field(
        validation_alias=AliasChoices("capability", "model", "alias"),
        serialization_alias="model",
    )
    messages: tuple[ChatMessage, ...]
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    tools: tuple[ToolDefinition, ...] | None = None
    tool_choice: Literal["none", "auto", "required"] | None = None
    response_format: dict[str, Any] | None = None

    @property
    def alias(self) -> CapabilityAlias:
        """Expose the capability alias using the domain terminology."""

        return self.capability

    @property
    def model(self) -> CapabilityAlias:
        """Expose the OpenAI-compatible model value to gateway clients."""

        return self.capability


class ResponseMetadata(BaseModel):
    """Normalized gateway metadata, nullable when a provider omits it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str | None = None
    model: str | None = None
    provider: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: float | None = None
    cost: float | None = None
    finish_reason: str | None = None


class GenerateResponse(BaseModel):
    """Plain text generation result with normalized metadata and tool calls."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    content: str | None = None
    metadata: ResponseMetadata = Field(default_factory=ResponseMetadata)
    tool_calls: tuple[ToolCall, ...] = ()


T = TypeVar("T")


class StructuredResponse[T](BaseModel):
    """Structured generation result containing a caller-owned typed value."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    data: T
    metadata: ResponseMetadata = Field(default_factory=ResponseMetadata)
    tool_calls: tuple[ToolCall, ...] = ()

    @classmethod
    def response_format(cls, response_model: type[BaseModel]) -> dict[str, Any]:
        """Build the strict OpenAI JSON-schema response format for a model."""

        return {
            "type": "json_schema",
            "json_schema": {
                "name": response_model.__name__,
                "strict": True,
                "schema": response_model.model_json_schema(),
            },
        }
