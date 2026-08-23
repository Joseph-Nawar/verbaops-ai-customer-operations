"""Behavioral tests for the VerbaOps HTTP LiteLLM gateway client."""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, SecretStr

from verbaops.config.settings import LLMSettings
from verbaops.llm import (
    CapabilityAlias,
    ChatMessage,
    GenerateRequest,
    LiteLLMClient,
    LLMAuthenticationError,
    LLMClient,
    LLMProtocolError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
    ToolDefinition,
)

SENTINEL_API_KEY = "sentinel-api-key-do-not-leak"
SENSITIVE_DETAIL = (
    "Authorization: Bearer sentinel-api-key-do-not-leak; raw gateway body; "
    "http://user:sentinel-api-key-do-not-leak@gateway.example/v1"
)


def make_settings() -> LLMSettings:
    return LLMSettings(
        base_url="http://gateway.example:4000/v1/",
        api_key=SecretStr(SENTINEL_API_KEY),
        timeout_seconds=2.5,
    )


def make_request(content: str = "Find order ORD-1") -> GenerateRequest:
    return GenerateRequest(
        capability=CapabilityAlias.AGENT_FAST,
        messages=(
            ChatMessage(role="system", content="You are concise."),
            ChatMessage(role="user", content=content),
        ),
        temperature=0.2,
        max_tokens=128,
        top_p=0.9,
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
        tool_choice="auto",
    )


def make_client(handler: Callable[[httpx.Request], httpx.Response]) -> LiteLLMClient:
    return LiteLLMClient(make_settings(), transport=httpx.MockTransport(handler))


def assert_safe(value: object) -> None:
    rendered = f"{value!s} {value!r}"
    for forbidden in (
        SENTINEL_API_KEY,
        "Authorization",
        "raw gateway body",
        "http://user:sentinel-api-key-do-not-leak@gateway.example/v1",
    ):
        assert forbidden not in rendered


@pytest.mark.asyncio
async def test_generate_serializes_exact_request_and_normalizes_gateway_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock_values = iter((10.0, 10.123))
    monkeypatch.setattr("verbaops.llm.litellm.perf_counter", lambda: next(clock_values))

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "http://gateway.example:4000/v1/chat/completions"
        assert request.headers["authorization"] == f"Bearer {SENTINEL_API_KEY}"
        assert request.headers["content-type"] == "application/json"
        assert json.loads(request.content) == {
            "model": "agent-fast",
            "messages": [
                {"role": "system", "content": "You are concise."},
                {"role": "user", "content": "Find order ORD-1"},
            ],
            "temperature": 0.2,
            "max_tokens": 128,
            "top_p": 0.9,
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
            "tool_choice": "auto",
        }
        return httpx.Response(
            200,
            headers={"x-request-id": "gateway-header-id"},
            json={
                "id": "gateway-body-id",
                "model": "gateway-model",
                "provider": "gateway-provider",
                "response_cost": 0.0025,
                "choices": [
                    {
                        "message": {
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
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 7,
                    "total_tokens": 18,
                },
            },
        )

    response = await make_client(handler).generate(make_request())

    assert response.content is None
    assert response.tool_calls[0].id == "call-1"
    assert response.tool_calls[0].name == "lookup_order"
    assert response.tool_calls[0].arguments == {"order_id": "ORD-1"}
    assert response.metadata.request_id == "gateway-header-id"
    assert response.metadata.capability_alias is CapabilityAlias.AGENT_FAST
    assert response.metadata.model == "gateway-model"
    assert response.metadata.provider == "gateway-provider"
    assert response.metadata.input_tokens == 11
    assert response.metadata.output_tokens == 7
    assert response.metadata.total_tokens == 18
    assert response.metadata.latency_ms == pytest.approx(123.0)
    assert response.metadata.cost == 0.0025
    assert response.metadata.finish_reason == "tool_calls"


@pytest.mark.asyncio
async def test_generate_leaves_omitted_gateway_metadata_nullable() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "plain text"}, "finish_reason": None}],
            },
        )

    response = await make_client(handler).generate(make_request())

    assert response.content == "plain text"
    assert response.tool_calls == ()
    assert response.metadata.request_id is None
    assert response.metadata.model is None
    assert response.metadata.provider is None
    assert response.metadata.input_tokens is None
    assert response.metadata.output_tokens is None
    assert response.metadata.total_tokens is None
    assert response.metadata.cost is None
    assert response.metadata.finish_reason is None
    assert response.metadata.latency_ms is not None


class TicketAnswer(BaseModel):
    status: str
    message: str


@pytest.mark.asyncio
async def test_generate_structured_sends_strict_schema_and_parses_pydantic_data() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["response_format"] == {
            "type": "json_schema",
            "json_schema": {
                "name": "TicketAnswer",
                "strict": True,
                "schema": TicketAnswer.model_json_schema(),
            },
        }
        return httpx.Response(
            200,
            json={
                "id": "structured-response",
                "choices": [
                    {
                        "message": {"content": '{"status":"open","message":"We are checking."}'},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    response = await make_client(handler).generate_structured(make_request(), TicketAnswer)

    assert response.data == TicketAnswer(status="open", message="We are checking.")
    assert response.metadata.request_id == "structured-response"
    assert response.metadata.finish_reason == "stop"
    assert response.tool_calls == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "response_model"),
    [
        (None, None),
        ({}, None),
        (
            {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "lookup_order",
                                        "arguments": "not-json",
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
            None,
        ),
        (
            {"choices": [{"message": {"content": '["not", "an", "object"]'}}]},
            TicketAnswer,
        ),
    ],
)
async def test_malformed_gateway_payloads_raise_protocol_errors(
    payload: dict[str, Any] | None,
    response_model: type[BaseModel] | None,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        if payload is None:
            return httpx.Response(200, content=b"{not-json")
        return httpx.Response(200, json=payload)

    client = make_client(handler)

    with pytest.raises(LLMProtocolError) as error:
        if response_model is None:
            await client.generate(make_request())
        else:
            await client.generate_structured(make_request(), response_model)

    assert_safe(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [
        (401, LLMAuthenticationError),
        (403, LLMAuthenticationError),
        (429, LLMRateLimitError),
        (500, LLMUnavailableError),
        (502, LLMUnavailableError),
        (503, LLMUnavailableError),
    ],
)
async def test_gateway_status_failures_are_mapped_to_safe_typed_errors(
    status_code: int,
    error_type: type[Exception],
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=SENSITIVE_DETAIL.encode())

    with pytest.raises(error_type) as error:
        await make_client(handler).generate(make_request())

    assert_safe(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("transport_error", "error_type"),
    [
        (httpx.TimeoutException(SENSITIVE_DETAIL), LLMTimeoutError),
        (httpx.ConnectError(SENSITIVE_DETAIL), LLMUnavailableError),
    ],
)
async def test_gateway_transport_failures_are_mapped_to_safe_typed_errors(
    transport_error: httpx.HTTPError,
    error_type: type[Exception],
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise transport_error

    with pytest.raises(error_type) as error:
        await make_client(handler).generate(make_request())

    assert_safe(error.value)


def test_public_client_and_all_typed_errors_redact_secrets_from_strings_and_reprs() -> None:
    client = make_client(lambda _request: httpx.Response(200, json={"choices": []}))

    assert isinstance(client, LLMClient)
    assert_safe(make_settings())
    assert_safe(client)
    for error_type in (
        LLMTimeoutError,
        LLMAuthenticationError,
        LLMRateLimitError,
        LLMUnavailableError,
        LLMProtocolError,
    ):
        assert_safe(error_type(SENSITIVE_DETAIL))
