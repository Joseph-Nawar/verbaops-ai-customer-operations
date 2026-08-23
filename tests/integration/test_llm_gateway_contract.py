"""Permanent real LiteLLM proxy contract tests backed by the local provider stub."""

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from pydantic import BaseModel, SecretStr

from verbaops.config.settings import LLMSettings
from verbaops.llm import (
    CapabilityAlias,
    ChatMessage,
    GenerateRequest,
    LiteLLMClient,
    LLMAuthenticationError,
    LLMUnavailableError,
    ToolDefinition,
)


class ContractAnswer(BaseModel):
    answer: str
    score: float


@pytest_asyncio.fixture(autouse=True)
async def isolate_commerce_test_state() -> AsyncIterator[None]:
    """Keep this gateway-only suite outside the sibling Commerce DB isolation fixture."""

    yield


def gateway_settings(
    *, api_key: str = "sk-test-gateway", timeout_seconds: float | None = None
) -> LLMSettings:
    """Read the runner-provided gateway settings without fallback credentials."""

    return LLMSettings(
        base_url=os.environ["VERBAOPS_LLM__BASE_URL"],
        api_key=SecretStr(api_key),
        timeout_seconds=(
            float(os.environ["VERBAOPS_LLM__TIMEOUT_SECONDS"])
            if timeout_seconds is None
            else timeout_seconds
        ),
    )


def request_for(marker: str, *, tools: tuple[ToolDefinition, ...] | None = None) -> GenerateRequest:
    """Build a request that selects one deterministic provider-stub response."""

    return GenerateRequest(
        capability=CapabilityAlias.AGENT_FAST,
        messages=(ChatMessage(role="user", content=marker),),
        tools=tools,
        tool_choice="auto" if tools is not None else None,
    )


@pytest.mark.llm_gateway_contract
@pytest.mark.asyncio
async def test_real_proxy_generates_plain_text_through_verbaops_client() -> None:
    response = await LiteLLMClient(gateway_settings()).generate(request_for("test:plain"))

    assert response.content == "deterministic-stub-response"
    assert response.metadata.capability_alias is CapabilityAlias.AGENT_FAST
    assert response.metadata.request_id is not None
    assert response.metadata.model is not None
    assert response.metadata.model != CapabilityAlias.AGENT_FAST.value
    assert response.metadata.cost is not None
    assert response.metadata.latency_ms is not None


@pytest.mark.llm_gateway_contract
@pytest.mark.asyncio
async def test_real_proxy_generates_and_parses_a_pydantic_structured_response() -> None:
    response = await LiteLLMClient(gateway_settings()).generate_structured(
        request_for("test:structured"), ContractAnswer
    )

    assert response.data == ContractAnswer(answer="deterministic", score=1.0)
    assert response.tool_calls == ()


@pytest.mark.llm_gateway_contract
@pytest.mark.asyncio
async def test_real_proxy_parses_tool_call_arguments() -> None:
    tools = (
        ToolDefinition(
            name="lookup_order",
            description="Look up a deterministic local order.",
            parameters={
                "type": "object",
                "properties": {"order_id": {"type": "string"}},
                "required": ["order_id"],
                "additionalProperties": False,
            },
        ),
    )

    response = await LiteLLMClient(gateway_settings()).generate(
        request_for("test:tool-call", tools=tools)
    )

    assert response.content is None
    assert response.tool_calls[0].id == "call_local_lookup"
    assert response.tool_calls[0].name == "lookup_order"
    assert response.tool_calls[0].arguments == {"order_id": "order-local-001", "action": "lookup"}


@pytest.mark.llm_gateway_contract
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("api_key", "marker", "error_type", "timeout_seconds"),
    [
        ("wrong-test-gateway-key", "test:plain", LLMAuthenticationError, None),
        ("sk-test-gateway", "test:server-error", LLMUnavailableError, 10.0),
    ],
)
async def test_real_proxy_normalizes_invalid_credentials_and_upstream_failures(
    api_key: str,
    marker: str,
    error_type: type[Exception],
    timeout_seconds: float | None,
) -> None:
    # This database-free LiteLLM configuration returns a safe 400 for an unknown key.
    with pytest.raises(error_type):
        await LiteLLMClient(
            gateway_settings(api_key=api_key, timeout_seconds=timeout_seconds)
        ).generate(request_for(marker))
