"""RED tests for explicit validation and sequential read-only tool execution."""

from dataclasses import dataclass, field
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr

from tests.support.fake_llm import ScriptedLLMClient
from verbaops.agent.context import AgentContext
from verbaops.agent.errors import (
    AgentBudgetExceededError,
    AgentProtocolError,
    AgentUnavailableError,
)
from verbaops.agent.graph import build_agent_graph
from verbaops.commerce.client import CommerceClient
from verbaops.config import CommerceSettings
from verbaops.conversations.domain import ConversationScope
from verbaops.conversations.service import ConversationService
from verbaops.llm.models import (
    CapabilityAlias,
    ChatMessage,
    GenerateResponse,
    ResponseMetadata,
    ToolCall,
)
from verbaops.tools.registry import build_commerce_read_registry


@dataclass
class RecordingConversationService:
    model_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)

    async def append_model_call(self, *args: Any, **kwargs: Any) -> None:
        self.model_calls.append({"args": args, "kwargs": kwargs})

    async def append_tool_invocation(self, *args: Any, **kwargs: Any) -> None:
        self.tool_calls.append({"args": args, "kwargs": kwargs})


def make_state(message: str = "Where is my order?") -> dict[str, Any]:
    return {
        "messages": [ChatMessage(role="user", content=message)],
        "pending_tool_calls": [],
        "last_tool_results": [],
        "model_call_count": 0,
        "tool_round_count": 0,
        "tool_call_count": 0,
        "validation_repair_count": 0,
        "final_response": None,
        "failure": None,
    }


def model_response(content: str | None, *calls: ToolCall) -> GenerateResponse:
    return GenerateResponse(
        content=content,
        tool_calls=calls,
        metadata=ResponseMetadata(capability_alias=CapabilityAlias.AGENT_FAST),
    )


def shipment_payload(order_id: UUID) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "order_id": str(order_id),
        "carrier": "Carrier",
        "tracking_number": "TRACK-1",
        "status": "in_transit",
        "estimated_delivery": "2026-08-25T10:00:00Z",
        "delivered_at": None,
        "delivery_slot_id": None,
    }


def make_context(
    llm: ScriptedLLMClient,
    service: RecordingConversationService,
    handler: Any,
) -> AgentContext:
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    commerce_client = CommerceClient(
        # The injected transport keeps this test entirely local and deterministic.
        settings=CommerceSettings(
            base_url="https://commerce.test",
            service_token=SecretStr("test-token"),
            timeout_seconds=1.0,
        ),
        http_client=http_client,
    )
    return AgentContext(
        conversation_id=uuid4(),
        agent_run_id=uuid4(),
        scope=ConversationScope(tenant_id=uuid4(), principal_id=uuid4()),
        customer_id=uuid4(),
        llm_client=llm,
        commerce_client=commerce_client,
        tool_registry=build_commerce_read_registry(),
        conversation_service=cast(ConversationService, service),
    )


def shipment_call(order_id: UUID, call_id: str = "shipment-1") -> ToolCall:
    return ToolCall(
        id=call_id,
        name="get_shipment_status",
        arguments={"order_id": str(order_id)},
    )


@pytest.mark.asyncio
async def test_successful_tool_loop_persists_trace_and_returns_grounded_answer() -> None:
    order_id = uuid4()
    llm = ScriptedLLMClient(
        [
            model_response(None, shipment_call(order_id)),
            model_response("Your order is in transit."),
        ]
    )
    service = RecordingConversationService()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=shipment_payload(order_id))

    context = make_context(llm, service, handler)
    result = await build_agent_graph().ainvoke(make_state(), context=context)

    assert result["final_response"] == "Your order is in transit."
    assert len(llm.requests) == 2
    assert len(service.model_calls) == 2
    assert len(service.tool_calls) == 1
    assert service.tool_calls[0]["kwargs"]["status"] == "succeeded"
    assert service.tool_calls[0]["kwargs"]["tool_name"] == "get_shipment_status"
    assert requests[0].method == "GET"


@pytest.mark.asyncio
async def test_multiple_tool_calls_execute_in_emitted_order() -> None:
    order_a, order_b = uuid4(), uuid4()
    calls: list[UUID] = []
    llm = ScriptedLLMClient(
        [
            model_response(None, shipment_call(order_a, "a"), shipment_call(order_b, "b")),
            model_response("Both shipments are in transit."),
        ]
    )
    service = RecordingConversationService()

    def handler(request: httpx.Request) -> httpx.Response:
        order_id = UUID(request.url.path.split("/")[3])
        calls.append(order_id)
        return httpx.Response(200, json=shipment_payload(order_id))

    result = await build_agent_graph().ainvoke(
        make_state(), context=make_context(llm, service, handler)
    )

    assert result["final_response"] == "Both shipments are in transit."
    assert calls == [order_a, order_b]
    assert [trace["kwargs"]["tool_call_id"] for trace in service.tool_calls] == ["a", "b"]


@pytest.mark.asyncio
async def test_unknown_tool_is_persisted_and_never_executed() -> None:
    llm = ScriptedLLMClient(
        [
            model_response(
                None,
                ToolCall(id="unknown-1", name="cancel_order", arguments={"order_id": str(uuid4())}),
            ),
            model_response("I can only provide read-only support."),
        ]
    )
    service = RecordingConversationService()
    commerce_calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal commerce_calls
        commerce_calls += 1
        return httpx.Response(500)

    result = await build_agent_graph().ainvoke(
        make_state(), context=make_context(llm, service, handler)
    )

    assert result["final_response"] == "I can only provide read-only support."
    assert commerce_calls == 0
    assert service.tool_calls[0]["kwargs"]["status"] == "failed"
    assert service.tool_calls[0]["kwargs"]["error_code"] == "unknown_tool"


@pytest.mark.asyncio
async def test_malformed_known_arguments_receive_one_repair_round() -> None:
    order_id = uuid4()
    llm = ScriptedLLMClient(
        [
            model_response(
                None,
                ToolCall(id="bad-1", name="get_shipment_status", arguments={"order_id": "bad"}),
            ),
            model_response(None, shipment_call(order_id, "good-1")),
            model_response("Your shipment is in transit."),
        ]
    )
    service = RecordingConversationService()

    result = await build_agent_graph().ainvoke(
        make_state(),
        context=make_context(
            llm,
            service,
            lambda _request: httpx.Response(200, json=shipment_payload(order_id)),
        ),
    )

    assert result["final_response"] == "Your shipment is in transit."
    assert len(llm.requests) == 3
    assert [trace["kwargs"]["status"] for trace in service.tool_calls] == [
        "failed",
        "succeeded",
    ]


@pytest.mark.asyncio
async def test_repeated_invalid_tool_calls_terminate_safely() -> None:
    invalid = ToolCall(id="bad", name="get_shipment_status", arguments={"order_id": "bad"})
    llm = ScriptedLLMClient([model_response(None, invalid), model_response(None, invalid)])
    service = RecordingConversationService()

    with pytest.raises(AgentProtocolError):
        await build_agent_graph().ainvoke(
            make_state(),
            context=make_context(llm, service, lambda _request: httpx.Response(500)),
        )

    assert len(service.tool_calls) == 2
    assert all(trace["kwargs"]["status"] == "failed" for trace in service.tool_calls)


@pytest.mark.asyncio
async def test_model_call_budget_is_hard() -> None:
    llm = ScriptedLLMClient([model_response("This response must not be called.")])
    service = RecordingConversationService()
    state = make_state()
    state["model_call_count"] = 4

    with pytest.raises(AgentBudgetExceededError):
        await build_agent_graph().ainvoke(
            state,
            context=make_context(
                llm,
                service,
                lambda _request: httpx.Response(
                    200,
                    json={"items": [], "limit": 1, "offset": 0, "has_more": False},
                ),
            ),
        )

    assert len(llm.requests) == 0


@pytest.mark.asyncio
async def test_tool_round_budget_is_hard() -> None:
    call = ToolCall(id="loop", name="search_products", arguments={"query": "phone", "limit": 1})
    llm = ScriptedLLMClient([model_response(None, call)] * 4)
    service = RecordingConversationService()

    with pytest.raises(AgentBudgetExceededError):
        await build_agent_graph().ainvoke(
            make_state(),
            context=make_context(
                llm,
                service,
                lambda _request: httpx.Response(
                    200,
                    json={"items": [], "limit": 1, "offset": 0, "has_more": False},
                ),
            ),
        )


@pytest.mark.asyncio
async def test_total_tool_call_budget_is_hard() -> None:
    calls = tuple(
        ToolCall(
            id=f"call-{index}",
            name="search_products",
            arguments={"query": "phone", "limit": 1},
        )
        for index in range(7)
    )
    llm = ScriptedLLMClient([model_response(None, *calls)])
    service = RecordingConversationService()

    with pytest.raises(AgentBudgetExceededError):
        await build_agent_graph().ainvoke(
            make_state(),
            context=make_context(
                llm,
                service,
                lambda _request: httpx.Response(
                    200,
                    json={"items": [], "limit": 1, "offset": 0, "has_more": False},
                ),
            ),
        )


@pytest.mark.asyncio
async def test_commerce_not_found_becomes_non_enumerating_data() -> None:
    order_id = uuid4()
    llm = ScriptedLLMClient(
        [
            model_response(None, shipment_call(order_id)),
            model_response("I could not locate that shipment."),
        ]
    )
    service = RecordingConversationService()

    result = await build_agent_graph().ainvoke(
        make_state(),
        context=make_context(
            llm,
            service,
            lambda _request: httpx.Response(404, content=b"secret backend detail"),
        ),
    )

    assert result["final_response"] == "I could not locate that shipment."
    tool_messages = [message for message in llm.requests[1].messages if message.role == "tool"]
    assert len(tool_messages) == 1
    assert "not_found" in (tool_messages[0].content or "")
    assert service.tool_calls[0]["kwargs"]["error_code"] == "commerce_not_found"


@pytest.mark.asyncio
async def test_commerce_unavailable_fails_without_allowing_model_to_improvise() -> None:
    llm = ScriptedLLMClient([model_response(None, shipment_call(uuid4()))])
    service = RecordingConversationService()

    with pytest.raises(AgentUnavailableError):
        await build_agent_graph().ainvoke(
            make_state(),
            context=make_context(
                llm,
                service,
                lambda _request: httpx.Response(503, content=b"secret backend detail"),
            ),
        )

    assert len(llm.requests) == 1
    assert service.tool_calls[0]["kwargs"]["status"] == "failed"
    assert service.tool_calls[0]["kwargs"]["error_code"] == "commerce_unavailable"
