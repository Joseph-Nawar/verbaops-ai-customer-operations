"""RED tests for AgentRuntime lifecycle orchestration."""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr

from tests.support.fake_llm import ScriptedLLMClient
from verbaops.agent.errors import AgentBusyError, AgentInputError, AgentUnavailableError
from verbaops.agent.runtime import AgentRuntime, AgentTurnResult
from verbaops.agent.versions import (
    GRAPH_VERSION,
    MAX_VISIBLE_HISTORY,
    PROMPT_VERSION,
    TOOL_SCHEMA_VERSION,
)
from verbaops.commerce.client import CommerceClient
from verbaops.config import CommerceSettings
from verbaops.conversations.domain import (
    AgentRunRecord,
    ConversationRecord,
    ConversationScope,
    MessageRecord,
    TurnCompletion,
    TurnStart,
)
from verbaops.conversations.errors import ConversationBusyError
from verbaops.conversations.service import ConversationService
from verbaops.llm.errors import LLMUnavailableError
from verbaops.llm.models import CapabilityAlias, GenerateResponse, ResponseMetadata, ToolCall
from verbaops.tools.registry import build_commerce_read_registry

NOW = datetime.now(UTC)


@dataclass
class RecordingConversationService:
    messages: list[MessageRecord] = field(default_factory=list)
    run: AgentRunRecord | None = None
    start_calls: list[dict[str, Any]] = field(default_factory=list)
    model_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    completed: list[TurnCompletion] = field(default_factory=list)
    failed: list[tuple[UUID, str]] = field(default_factory=list)
    busy: bool = False

    async def start_turn(
        self, scope: ConversationScope, conversation_id: UUID, content: str, **kwargs: Any
    ) -> TurnStart:
        if self.busy:
            raise ConversationBusyError()
        self.start_calls.append(
            {"scope": scope, "conversation_id": conversation_id, "content": content, **kwargs}
        )
        sequence = len(self.messages) + 1
        user_message = MessageRecord(uuid4(), conversation_id, sequence, "user", content, NOW)
        self.messages.append(user_message)
        conversation = ConversationRecord(
            conversation_id,
            scope.tenant_id,
            scope.principal_id,
            uuid4(),
            NOW,
            NOW,
        )
        self.run = AgentRunRecord(
            uuid4(),
            conversation_id,
            user_message.id,
            None,
            "running",
            kwargs["graph_version"],
            kwargs["prompt_version"],
            kwargs["tool_schema_version"],
            NOW,
            None,
            None,
        )
        return TurnStart(conversation, user_message, self.run)

    async def list_messages(
        self, _scope: ConversationScope, _conversation_id: UUID
    ) -> list[MessageRecord]:
        return list(self.messages)

    async def append_model_call(self, *args: Any, **kwargs: Any) -> Any:
        self.model_calls.append({"args": args, "kwargs": kwargs})
        return None

    async def append_tool_invocation(self, *args: Any, **kwargs: Any) -> Any:
        self.tool_calls.append({"args": args, "kwargs": kwargs})
        return None

    async def complete_turn(
        self, _scope: ConversationScope, conversation_id: UUID, agent_run_id: UUID, content: str
    ) -> TurnCompletion:
        message = MessageRecord(
            uuid4(), conversation_id, len(self.messages) + 1, "assistant", content, NOW
        )
        self.messages.append(message)
        assert self.run is not None
        self.run = AgentRunRecord(
            self.run.id,
            self.run.conversation_id,
            self.run.user_message_id,
            message.id,
            "completed",
            self.run.graph_version,
            self.run.prompt_version,
            self.run.tool_schema_version,
            self.run.started_at,
            NOW,
            None,
        )
        completion = TurnCompletion(message, self.run)
        self.completed.append(completion)
        return completion

    async def fail_turn(
        self, _scope: ConversationScope, _conversation_id: UUID, agent_run_id: UUID, error_code: str
    ) -> AgentRunRecord:
        self.failed.append((agent_run_id, error_code))
        assert self.run is not None
        self.run = AgentRunRecord(
            self.run.id,
            self.run.conversation_id,
            self.run.user_message_id,
            None,
            "failed",
            self.run.graph_version,
            self.run.prompt_version,
            self.run.tool_schema_version,
            self.run.started_at,
            NOW,
            error_code,
        )
        return self.run


def response(content: str | None, *tool_calls: ToolCall) -> GenerateResponse:
    return GenerateResponse(
        content=content,
        tool_calls=tool_calls,
        metadata=ResponseMetadata(capability_alias=CapabilityAlias.AGENT_FAST),
    )


def make_runtime(
    service: RecordingConversationService,
    llm: ScriptedLLMClient,
    *,
    deadline_seconds: float = 45.0,
    commerce_handler: Any | None = None,
) -> AgentRuntime:
    handler = commerce_handler or (lambda _request: httpx.Response(500))
    commerce = CommerceClient(
        CommerceSettings(
            base_url="https://commerce.test",
            service_token=SecretStr("test-token"),
            timeout_seconds=1.0,
        ),
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return AgentRuntime(
        conversation_service=cast(ConversationService, service),
        llm_client=llm,
        commerce_client=commerce,
        tool_registry=build_commerce_read_registry(),
        deadline_seconds=deadline_seconds,
    )


class CapturingGraph:
    def __init__(self) -> None:
        self.initial_state: dict[str, Any] | None = None

    async def ainvoke(
        self, state: dict[str, Any], *, context: Any, config: dict[str, Any]
    ) -> dict[str, Any]:
        del context, config
        self.initial_state = state
        return {"final_response": "bounded response"}


def scope() -> ConversationScope:
    return ConversationScope(tenant_id=uuid4(), principal_id=uuid4())


@pytest.mark.asyncio
async def test_two_turn_clarification_then_shipment_lookup_persists_lifecycle() -> None:
    order_id = uuid4()
    llm = ScriptedLLMClient(
        [
            response("Please provide your order ID."),
            response(
                None,
                ToolCall(
                    id="ship-1", name="get_shipment_status", arguments={"order_id": str(order_id)}
                ),
            ),
            response("Your shipment is in transit."),
        ]
    )
    service = RecordingConversationService()
    runtime = make_runtime(
        service,
        llm,
        commerce_handler=lambda _request: httpx.Response(
            200,
            json={
                "order_id": str(order_id),
                "id": str(uuid4()),
                "status": "in_transit",
                "carrier": "Acme",
                "tracking_number": "TRACK-1",
                "estimated_delivery": None,
                "delivered_at": None,
                "delivery_slot_id": None,
            },
        ),
    )
    conversation_id = uuid4()
    current_scope = scope()

    first = await runtime.run_turn(current_scope, conversation_id, uuid4(), "Where is my order?")
    second = await runtime.run_turn(current_scope, conversation_id, uuid4(), str(order_id))

    assert isinstance(first, AgentTurnResult)
    assert first.content == "Please provide your order ID."
    assert second.content == "Your shipment is in transit."
    assert len(service.completed) == 2
    assert len(service.tool_calls) == 1
    assert [message.role for message in service.messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert all(call["graph_version"] == GRAPH_VERSION for call in service.start_calls)
    assert all(call["prompt_version"] == PROMPT_VERSION for call in service.start_calls)
    assert all(call["tool_schema_version"] == TOOL_SCHEMA_VERSION for call in service.start_calls)


@pytest.mark.asyncio
async def test_runtime_bounds_only_initial_persisted_visible_history() -> None:
    service = RecordingConversationService(
        messages=[
            MessageRecord(uuid4(), uuid4(), index + 1, "user", f"history-{index}", NOW)
            for index in range(30)
        ]
    )
    graph = CapturingGraph()
    runtime = AgentRuntime(
        conversation_service=cast(ConversationService, service),
        llm_client=ScriptedLLMClient([]),
        commerce_client=cast(CommerceClient, object()),
        graph=graph,
    )

    await runtime.run_turn(scope(), uuid4(), uuid4(), "current message")

    assert graph.initial_state is not None
    messages = graph.initial_state["messages"]
    assert len(messages) == MAX_VISIBLE_HISTORY
    assert messages[0].content == "history-11"
    assert messages[-1].content == "current message"


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["", "   ", "x" * 8001])
async def test_run_turn_rejects_invalid_user_content_before_persistence(content: str) -> None:
    service = RecordingConversationService()
    runtime = make_runtime(service, ScriptedLLMClient([response("unused")]))

    with pytest.raises(AgentInputError):
        await runtime.run_turn(scope(), uuid4(), uuid4(), content)

    assert service.start_calls == []


@pytest.mark.asyncio
async def test_busy_conversation_maps_to_agent_busy_without_failure_write() -> None:
    service = RecordingConversationService(busy=True)
    runtime = make_runtime(service, ScriptedLLMClient([]))

    with pytest.raises(AgentBusyError):
        await runtime.run_turn(scope(), uuid4(), uuid4(), "Hello")

    assert service.failed == []


@pytest.mark.asyncio
async def test_llm_failure_fails_run_without_fabricated_assistant_message() -> None:
    class FailingLLM(ScriptedLLMClient):
        async def generate(self, request: Any) -> GenerateResponse:
            self.requests.append(request)
            raise LLMUnavailableError()

    service = RecordingConversationService()
    runtime = make_runtime(service, FailingLLM([]))

    with pytest.raises(AgentUnavailableError):
        await runtime.run_turn(scope(), uuid4(), uuid4(), "Where is my order?")

    assert service.completed == []
    assert len(service.failed) == 1
    assert [message.role for message in service.messages] == ["user"]


@pytest.mark.asyncio
async def test_deadline_fails_run_while_external_call_is_slow() -> None:
    class SlowLLM(ScriptedLLMClient):
        async def generate(self, request: Any) -> GenerateResponse:
            self.requests.append(request)
            await asyncio.sleep(0.05)
            return response("too late")

    service = RecordingConversationService()
    runtime = make_runtime(service, SlowLLM([]), deadline_seconds=0.001)

    with pytest.raises(AgentUnavailableError):
        await runtime.run_turn(scope(), uuid4(), uuid4(), "Hello")

    assert service.completed == []
    assert service.failed[0][1] == "agent_unavailable"
