"""RED tests for the direct M3D StateGraph and model node."""

from dataclasses import dataclass, field
from typing import Any, cast
from uuid import uuid4

import pytest

from tests.support.fake_llm import ScriptedLLMClient
from verbaops.agent.context import AgentContext
from verbaops.agent.errors import AgentProtocolError
from verbaops.agent.graph import build_agent_graph
from verbaops.agent.versions import MAX_VISIBLE_HISTORY
from verbaops.commerce.client import CommerceClient
from verbaops.conversations.domain import ConversationScope
from verbaops.conversations.service import ConversationService
from verbaops.llm.models import (
    CapabilityAlias,
    ChatMessage,
    GenerateResponse,
    ResponseMetadata,
)
from verbaops.tools.registry import build_commerce_read_registry


@dataclass
class RecordingConversationService:
    model_calls: list[dict[str, Any]] = field(default_factory=list)

    async def append_model_call(self, *args: Any, **kwargs: Any) -> None:
        self.model_calls.append({"args": args, "kwargs": kwargs})


def make_context(llm_client: ScriptedLLMClient) -> AgentContext:
    return AgentContext(
        conversation_id=uuid4(),
        agent_run_id=uuid4(),
        scope=ConversationScope(tenant_id=uuid4(), principal_id=uuid4()),
        customer_id=uuid4(),
        llm_client=llm_client,
        commerce_client=cast(CommerceClient, object()),
        tool_registry=build_commerce_read_registry(),
        conversation_service=cast(ConversationService, RecordingConversationService()),
    )


def response(content: str | None, *, tool_calls: tuple[Any, ...] = ()) -> GenerateResponse:
    return GenerateResponse(
        content=content,
        tool_calls=tool_calls,
        metadata=ResponseMetadata(capability_alias=CapabilityAlias.AGENT_FAST),
    )


@pytest.mark.asyncio
async def test_compiled_graph_has_exact_bounded_topology() -> None:
    graph = build_agent_graph()
    graph_nodes = set(graph.get_graph().nodes)
    graph_edges = {(edge.source, edge.target) for edge in graph.get_graph().edges}

    assert {
        "__start__",
        "agent",
        "validate_tool_calls",
        "execute_tools",
        "finalize",
        "__end__",
    } <= graph_nodes
    assert ("__start__", "agent") in graph_edges
    assert ("agent", "validate_tool_calls") in graph_edges
    assert ("agent", "finalize") in graph_edges
    assert ("validate_tool_calls", "execute_tools") in graph_edges
    assert ("execute_tools", "agent") in graph_edges
    assert ("finalize", "__end__") in graph_edges


@pytest.mark.asyncio
async def test_model_request_exposes_exactly_the_five_read_only_tool_schemas() -> None:
    llm = ScriptedLLMClient([response("Please provide the order ID.")])
    context = make_context(llm)

    result = await build_agent_graph().ainvoke(
        {
            "messages": [ChatMessage(role="user", content="Where is my order?")],
            "pending_tool_calls": [],
            "last_tool_results": [],
            "model_call_count": 0,
            "tool_round_count": 0,
            "tool_call_count": 0,
            "validation_repair_count": 0,
            "final_response": None,
            "failure": None,
        },
        context=context,
    )

    assert result["final_response"] == "Please provide the order ID."
    assert llm.requests[0].capability is CapabilityAlias.AGENT_FAST
    assert [tool.name for tool in llm.requests[0].tools or ()] == [
        "get_order_status",
        "get_shipment_status",
        "get_refund_status",
        "search_products",
        "list_delivery_slots",
    ]
    forbidden = {"tenant_id", "principal_id", "customer_id", "roles", "service_token"}
    for tool in llm.requests[0].tools or ():
        assert set(tool.parameters.get("properties", {})).isdisjoint(forbidden)


@pytest.mark.asyncio
async def test_model_history_is_bounded_to_latest_customer_visible_messages() -> None:
    llm = ScriptedLLMClient([response("I need more information.")])
    context = make_context(llm)
    history = [
        ChatMessage(role="user" if index % 2 == 0 else "assistant", content=f"message-{index}")
        for index in range(30)
    ]

    await build_agent_graph().ainvoke(
        {
            "messages": history,
            "pending_tool_calls": [],
            "last_tool_results": [],
            "model_call_count": 0,
            "tool_round_count": 0,
            "tool_call_count": 0,
            "validation_repair_count": 0,
            "final_response": None,
            "failure": None,
        },
        context=context,
    )

    visible_messages = [message for message in llm.requests[0].messages if message.role != "system"]
    assert len(visible_messages) == MAX_VISIBLE_HISTORY
    assert visible_messages[0].content == "message-10"
    assert visible_messages[-1].content == "message-29"


@pytest.mark.asyncio
async def test_model_response_without_content_or_tool_calls_is_protocol_failure() -> None:
    llm = ScriptedLLMClient([response(None)])

    with pytest.raises(AgentProtocolError):
        await build_agent_graph().ainvoke(
            {
                "messages": [ChatMessage(role="user", content="Hello")],
                "pending_tool_calls": [],
                "last_tool_results": [],
                "model_call_count": 0,
                "tool_round_count": 0,
                "tool_call_count": 0,
                "validation_repair_count": 0,
                "final_response": None,
                "failure": None,
            },
            context=make_context(llm),
        )


@pytest.mark.asyncio
async def test_successful_model_call_persists_normalized_metadata() -> None:
    service = RecordingConversationService()
    llm = ScriptedLLMClient([response("Clarify this")])
    context = make_context(llm)
    context = AgentContext(
        conversation_id=context.conversation_id,
        agent_run_id=context.agent_run_id,
        scope=context.scope,
        customer_id=context.customer_id,
        llm_client=llm,
        commerce_client=context.commerce_client,
        tool_registry=context.tool_registry,
        conversation_service=cast(ConversationService, service),
    )

    await build_agent_graph().ainvoke(
        {
            "messages": [ChatMessage(role="user", content="Hello")],
            "pending_tool_calls": [],
            "last_tool_results": [],
            "model_call_count": 0,
            "tool_round_count": 0,
            "tool_call_count": 0,
            "validation_repair_count": 0,
            "final_response": None,
            "failure": None,
        },
        context=context,
    )

    assert len(service.model_calls) == 1
    assert service.model_calls[0]["kwargs"]["status"] == "succeeded"
