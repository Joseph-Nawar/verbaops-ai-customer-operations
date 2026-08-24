"""M3D persistence integration tests through the real read-agent runtime."""

from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.support.fake_llm import ScriptedLLMClient
from verbaops.agent.errors import AgentUnavailableError
from verbaops.agent.runtime import AgentRuntime
from verbaops.agent.versions import GRAPH_VERSION, PROMPT_VERSION, TOOL_SCHEMA_VERSION
from verbaops.commerce.client import CommerceClient
from verbaops.config import CommerceSettings
from verbaops.conversations.domain import ConversationScope
from verbaops.conversations.service import ConversationService
from verbaops.llm.errors import LLMUnavailableError
from verbaops.llm.models import (
    CapabilityAlias,
    GenerateRequest,
    GenerateResponse,
    ResponseMetadata,
    ToolCall,
)
from verbaops.tools.registry import build_commerce_read_registry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.m3d,
    pytest.mark.usefixtures("clean_verbaops_tables"),
]


def _response(content: str | None, *tool_calls: ToolCall) -> GenerateResponse:
    return GenerateResponse(
        content=content,
        tool_calls=tool_calls,
        metadata=ResponseMetadata(
            capability_alias=CapabilityAlias.AGENT_FAST,
            gateway_request_id="gateway-call-1",
            gateway_model_id="deployment-1",
            model="provider/model-1",
            provider="deterministic",
            input_tokens=20,
            output_tokens=8,
            total_tokens=28,
            latency_ms=4.5,
            cost_usd=None,
            finish_reason="stop",
        ),
    )


def _scope() -> ConversationScope:
    return ConversationScope(tenant_id=uuid4(), principal_id=uuid4())


def _commerce_client(order_id: UUID) -> tuple[CommerceClient, httpx.AsyncClient]:
    payload = {
        "id": str(uuid4()),
        "order_id": str(order_id),
        "carrier": "Acme",
        "tracking_number": "TRACK-1",
        "status": "in_transit",
        "estimated_delivery": None,
        "delivered_at": None,
        "delivery_slot_id": None,
    }
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))
    )
    return CommerceClient(
        CommerceSettings(
            base_url="https://commerce.test",
            service_token=SecretStr("test-token"),
            timeout_seconds=1.0,
        ),
        http_client,
    ), http_client


@pytest.mark.asyncio
async def test_runtime_persists_versions_traces_and_visible_history(
    service: ConversationService, engine: AsyncEngine
) -> None:
    order_id = uuid4()
    llm = ScriptedLLMClient(
        [
            _response("Please provide your order ID."),
            _response(
                None,
                ToolCall(
                    id="shipment-call-1",
                    name="get_shipment_status",
                    arguments={"order_id": str(order_id)},
                ),
            ),
            _response("Your shipment is in transit."),
        ]
    )
    commerce, http_client = _commerce_client(order_id)
    scope = _scope()
    customer_id = uuid4()
    conversation = await service.create_conversation(scope, customer_id=customer_id)
    runtime = AgentRuntime(
        conversation_service=service,
        llm_client=llm,
        commerce_client=commerce,
        tool_registry=build_commerce_read_registry(),
    )

    try:
        first = await runtime.run_turn(scope, conversation.id, customer_id, "Where is my order?")
        second = await runtime.run_turn(scope, conversation.id, customer_id, str(order_id))
    finally:
        await http_client.aclose()

    assert first.content == "Please provide your order ID."
    assert second.content == "Your shipment is in transit."
    messages = await service.list_messages(scope, conversation.id)
    assert [(message.role, message.content) for message in messages] == [
        ("user", "Where is my order?"),
        ("assistant", "Please provide your order ID."),
        ("user", str(order_id)),
        ("assistant", "Your shipment is in transit."),
    ]

    async with engine.connect() as connection:
        runs = [
            tuple(row)
            for row in (
                await connection.execute(
                    text(
                        "SELECT status, graph_version, prompt_version, tool_schema_version "
                        "FROM agent_runs WHERE conversation_id = :conversation_id ORDER BY started_at"
                    ),
                    {"conversation_id": conversation.id},
                )
            ).all()
        ]
        model_calls = (
            await connection.execute(
                text(
                    "SELECT capability_alias, gateway_request_id, gateway_model_id, model, provider, "
                    "input_tokens, output_tokens, total_tokens, latency_ms, cost_usd, finish_reason "
                    "FROM model_calls ORDER BY created_at"
                )
            )
        ).all()
        tool_calls = (
            await connection.execute(
                text(
                    "SELECT tool_call_id, tool_name, status, arguments_json, result_json "
                    "FROM tool_invocations ORDER BY created_at"
                )
            )
        ).all()

    assert runs == [
        ("completed", GRAPH_VERSION, PROMPT_VERSION, TOOL_SCHEMA_VERSION),
        ("completed", GRAPH_VERSION, PROMPT_VERSION, TOOL_SCHEMA_VERSION),
    ]
    assert len(model_calls) == 3
    assert model_calls[0] == (
        "agent-fast",
        "gateway-call-1",
        "deployment-1",
        "provider/model-1",
        "deterministic",
        20,
        8,
        28,
        4.5,
        None,
        "stop",
    )
    assert len(tool_calls) == 1
    assert tool_calls[0][0:3] == ("shipment-call-1", "get_shipment_status", "succeeded")
    assert tool_calls[0][3] == {"order_id": str(order_id)}
    assert tool_calls[0][4]["status"] == "in_transit"


@pytest.mark.asyncio
async def test_runtime_failure_persists_failed_model_call_without_assistant(
    service: ConversationService, engine: AsyncEngine
) -> None:
    class FailingLLM:
        async def generate(self, _request: GenerateRequest) -> GenerateResponse:
            raise LLMUnavailableError()

        async def generate_structured[T](
            self, _request: GenerateRequest, _response_model: type[T]
        ) -> Any:
            raise AssertionError("structured generation is not used")

    scope = _scope()
    conversation = await service.create_conversation(scope)
    commerce, http_client = _commerce_client(uuid4())
    runtime = AgentRuntime(
        conversation_service=service,
        llm_client=FailingLLM(),  # type: ignore[arg-type]
        commerce_client=commerce,
    )

    try:
        with pytest.raises(AgentUnavailableError):
            await runtime.run_turn(scope, conversation.id, uuid4(), "Try again")
    finally:
        await http_client.aclose()

    messages = await service.list_messages(scope, conversation.id)
    assert [(message.role, message.content) for message in messages] == [("user", "Try again")]
    async with engine.connect() as connection:
        run = (
            await connection.execute(
                text("SELECT status, assistant_message_id, error_code FROM agent_runs")
            )
        ).one()
        model_call = (
            await connection.execute(
                text("SELECT capability_alias, status, error_code FROM model_calls")
            )
        ).one()
    assert run == ("failed", None, "agent_unavailable")
    assert model_call == ("agent-fast", "failed", "llm_unavailable")
