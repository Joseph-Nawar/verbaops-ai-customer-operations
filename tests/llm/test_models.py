"""Behavioral tests for VerbaOps-owned LLM request and response models."""

from typing import Any, cast

import pytest
from pydantic import BaseModel, RootModel, ValidationError

from verbaops.llm.models import (
    CapabilityAlias,
    ChatMessage,
    GenerateRequest,
    ResponseMetadata,
    StructuredResponse,
    ToolCall,
    ToolDefinition,
)


def test_capability_aliases_are_locked() -> None:
    assert [alias.value for alias in CapabilityAlias] == [
        "agent-fast",
        "agent-reasoning",
        "eval-judge",
        "embedding-multilingual",
    ]


def test_generate_request_serializes_to_openai_chat_completions_json() -> None:
    request = GenerateRequest(
        capability=CapabilityAlias.AGENT_FAST,
        messages=(
            ChatMessage(role="system", content="You are concise."),
            ChatMessage(role="user", content="Find my order."),
            ChatMessage(
                role="assistant",
                content=None,
                tool_calls=(
                    ToolCall(
                        id="call-1",
                        name="lookup_order",
                        arguments={"order_id": "ORD-1"},
                    ),
                ),
            ),
        ),
        temperature=0.2,
        max_tokens=128,
        tools=(
            ToolDefinition(
                name="lookup_order",
                description="Look up an order.",
                parameters={
                    "type": "object",
                    "properties": {"order_id": {"type": "string"}},
                    "required": ["order_id"],
                    "additionalProperties": False,
                },
            ),
        ),
    )

    assert request.model_dump(mode="json", by_alias=True, exclude_none=True) == {
        "model": "agent-fast",
        "messages": [
            {"role": "system", "content": "You are concise."},
            {"role": "user", "content": "Find my order."},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "lookup_order",
                            "arguments": '{"order_id":"ORD-1"}',
                        },
                    }
                ],
            },
        ],
        "temperature": 0.2,
        "max_tokens": 128,
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "lookup_order",
                    "description": "Look up an order.",
                    "parameters": {
                        "type": "object",
                        "properties": {"order_id": {"type": "string"}},
                        "required": ["order_id"],
                        "additionalProperties": False,
                    },
                },
            }
        ],
    }


class TicketAnswer(BaseModel):
    status: str
    message: str


class NestedAnswer(BaseModel):
    details: TicketAnswer
    note: str | None = None


def test_structured_response_format_is_strict_json_schema() -> None:
    response_format = StructuredResponse.response_format(TicketAnswer)

    assert response_format == {
        "type": "json_schema",
        "json_schema": {
            "name": "TicketAnswer",
            "strict": True,
            "schema": {
                **TicketAnswer.model_json_schema(),
                "additionalProperties": False,
            },
        },
    }

    response = StructuredResponse[TicketAnswer](
        data=TicketAnswer(status="open", message="We are checking."),
    )
    assert response.data.status == "open"


def test_strict_schema_conversion_is_recursive_and_removes_defaults() -> None:
    schema = StructuredResponse.response_format(NestedAnswer)["json_schema"]["schema"]

    assert schema["required"] == ["details", "note"]
    assert "default" not in schema["properties"]["note"]
    assert schema["$defs"]["TicketAnswer"]["additionalProperties"] is False


def test_strict_schema_rejects_mapping_fields_and_non_object_roots() -> None:
    class MappingAnswer(BaseModel):
        labels: dict[str, str]

    class RootAnswer(RootModel[list[str]]):
        pass

    with pytest.raises(ValueError, match="mapping fields"):
        StructuredResponse.response_format(MappingAnswer)
    with pytest.raises(ValueError, match="object root"):
        StructuredResponse.response_format(RootAnswer)


def test_response_metadata_fields_are_nullable() -> None:
    metadata = ResponseMetadata()

    assert metadata.capability_alias is None
    assert metadata.gateway_request_id is None
    assert metadata.gateway_model_id is None
    assert metadata.model is None
    assert metadata.provider is None
    assert metadata.input_tokens is None
    assert metadata.output_tokens is None
    assert metadata.total_tokens is None
    assert metadata.latency_ms is None
    assert metadata.cost_usd is None
    assert metadata.finish_reason is None


def test_response_metadata_retains_capability_alias() -> None:
    metadata = ResponseMetadata(capability_alias=CapabilityAlias.AGENT_FAST)

    assert metadata.capability_alias is CapabilityAlias.AGENT_FAST


def test_llm_models_are_frozen_and_reject_extra_fields() -> None:
    message = ChatMessage(role="user", content="hello")

    with pytest.raises(ValidationError):
        message.content = "changed"

    with pytest.raises(ValidationError):
        ChatMessage.model_validate(
            cast(
                dict[str, Any],
                {"role": "user", "content": "hello", "unexpected": "value"},
            )
        )
