"""RED-first tests for voice AgentRuntime provenance."""

from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from verbaops.agent.errors import AgentInputError, AgentVoiceTurnFailedError
from verbaops.agent.runtime import AgentRuntime
from verbaops.auth.context import Role, TrustedContext
from verbaops.commerce.client import CommerceClient
from verbaops.conversations.domain import (
    AgentRunRecord,
    ConversationRecord,
    ConversationScope,
    InteractionMode,
    MessageRecord,
    TurnCompletion,
    TurnStart,
    VoiceTurnClaim,
)
from verbaops.conversations.service import ConversationService
from verbaops.llm.client import LLMClient

NOW = datetime.now(UTC)


@dataclass
class RecordingVoiceConversationService:
    start_calls: list[dict[str, Any]]
    messages: list[MessageRecord]
    run: AgentRunRecord | None = None

    async def start_turn(
        self, scope: ConversationScope, conversation_id: UUID, content: str, **kwargs: Any
    ) -> TurnStart:
        self.start_calls.append(kwargs)
        message = MessageRecord(uuid4(), conversation_id, 1, "user", content, NOW)
        self.messages.append(message)
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
            message.id,
            None,
            "running",
            kwargs["graph_version"],
            kwargs["prompt_version"],
            kwargs["tool_schema_version"],
            NOW,
            None,
            None,
            kwargs.get("interaction_mode", InteractionMode.TEXT),
            kwargs.get("voice_session_id"),
            kwargs.get("voice_turn_id"),
        )
        return TurnStart(conversation, message, self.run)

    async def list_messages(
        self, _scope: ConversationScope, _conversation_id: UUID
    ) -> list[MessageRecord]:
        return list(self.messages)

    async def start_voice_turn(self, *args: Any, **kwargs: Any) -> VoiceTurnClaim:
        kwargs.setdefault("interaction_mode", InteractionMode.VOICE)
        return VoiceTurnClaim(turn_start=await self.start_turn(*args, **kwargs))

    async def complete_turn(
        self, _scope: ConversationScope, conversation_id: UUID, _run_id: UUID, content: str
    ) -> TurnCompletion:
        assert self.run is not None
        assistant = MessageRecord(uuid4(), conversation_id, 2, "assistant", content, NOW)
        self.messages.append(assistant)
        self.run = AgentRunRecord(
            self.run.id,
            self.run.conversation_id,
            self.run.user_message_id,
            assistant.id,
            "completed",
            self.run.graph_version,
            self.run.prompt_version,
            self.run.tool_schema_version,
            self.run.started_at,
            NOW,
            None,
            self.run.interaction_mode,
            self.run.voice_session_id,
            self.run.voice_turn_id,
        )
        return TurnCompletion(assistant, self.run)

    async def fail_turn(self, *_args: Any, **_kwargs: Any) -> AgentRunRecord:
        raise AssertionError("the test graph should not fail")


class CapturingGraph:
    def __init__(self) -> None:
        self.context: Any | None = None

    async def ainvoke(
        self, _state: dict[str, Any], *, context: Any, config: dict[str, Any]
    ) -> dict[str, Any]:
        del config
        self.context = context
        return {"final_response": "voice response"}


@dataclass
class ReplayConversationService(RecordingVoiceConversationService):
    replay: Any | None = None

    async def start_voice_turn(self, *_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(turn_start=None, replay=self.replay)


def _trusted_context() -> TrustedContext:
    return TrustedContext(
        tenant_id=uuid4(),
        principal_id=uuid4(),
        customer_id=uuid4(),
        roles=frozenset({Role.CUSTOMER, Role.SUPPORT_AGENT}),
    )


def _runtime(service: RecordingVoiceConversationService, graph: CapturingGraph) -> AgentRuntime:
    return AgentRuntime(
        conversation_service=cast(ConversationService, service),
        llm_client=cast(LLMClient, object()),
        commerce_client=cast(CommerceClient, object()),
        graph=graph,
    )


@pytest.mark.asyncio
async def test_voice_turn_persists_provenance_and_preserves_trusted_authority() -> None:
    service = RecordingVoiceConversationService([], [])
    graph = CapturingGraph()
    context = _trusted_context()
    voice_session_id = uuid4()
    voice_turn_id = uuid4()

    result = await _runtime(service, graph).run_turn(
        context,
        uuid4(),
        "Where is my order?",
        interaction_mode=InteractionMode.VOICE,
        voice_session_id=voice_session_id,
        voice_turn_id=voice_turn_id,
    )

    assert service.start_calls[0]["interaction_mode"] is InteractionMode.VOICE
    assert service.start_calls[0]["voice_session_id"] == voice_session_id
    assert service.start_calls[0]["voice_turn_id"] == voice_turn_id
    assert result.agent_run.interaction_mode is InteractionMode.VOICE
    assert result.agent_run.voice_session_id == voice_session_id
    assert result.agent_run.voice_turn_id == voice_turn_id
    assert graph.context.interaction_mode is InteractionMode.VOICE
    assert graph.context.voice_session_id == voice_session_id
    assert graph.context.voice_turn_id == voice_turn_id
    assert graph.context.trusted_context == context
    assert graph.context.trusted_context.roles == context.roles


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("interaction_mode", "voice_session_id", "voice_turn_id"),
    [
        (InteractionMode.TEXT, uuid4(), None),
        (InteractionMode.TEXT, None, uuid4()),
        (InteractionMode.VOICE, None, uuid4()),
        (InteractionMode.VOICE, uuid4(), None),
    ],
)
async def test_runtime_rejects_partial_or_mismatched_voice_provenance(
    interaction_mode: InteractionMode,
    voice_session_id: UUID | None,
    voice_turn_id: UUID | None,
) -> None:
    service = RecordingVoiceConversationService([], [])

    with pytest.raises(AgentInputError):
        await _runtime(service, CapturingGraph()).run_turn(
            _trusted_context(),
            uuid4(),
            "hello",
            interaction_mode=interaction_mode,
            voice_session_id=voice_session_id,
            voice_turn_id=voice_turn_id,
        )

    assert service.start_calls == []


@pytest.mark.asyncio
async def test_text_turn_keeps_safe_default_provenance() -> None:
    service = RecordingVoiceConversationService([], [])
    graph = CapturingGraph()

    result = await _runtime(service, graph).run_turn(_trusted_context(), uuid4(), "hello")

    assert service.start_calls[0]["interaction_mode"] is InteractionMode.TEXT
    assert service.start_calls[0]["voice_session_id"] is None
    assert service.start_calls[0]["voice_turn_id"] is None
    assert result.agent_run.interaction_mode is InteractionMode.TEXT
    assert result.agent_run.voice_session_id is None
    assert result.agent_run.voice_turn_id is None
    assert graph.context.interaction_mode is InteractionMode.TEXT


@pytest.mark.asyncio
async def test_completed_voice_turn_replays_durable_result_without_graph_invocation() -> None:
    conversation_id = uuid4()
    run_id = uuid4()
    user_message = MessageRecord(uuid4(), conversation_id, 1, "user", "hello", NOW)
    assistant_message = MessageRecord(uuid4(), conversation_id, 2, "assistant", "durable", NOW)
    run = AgentRunRecord(
        run_id,
        conversation_id,
        user_message.id,
        assistant_message.id,
        "completed",
        "graph-v1",
        "prompt-v1",
        "tools-v1",
        NOW,
        NOW,
        None,
        InteractionMode.VOICE,
        uuid4(),
        uuid4(),
    )
    service = ReplayConversationService(
        [],
        [],
        replay=SimpleNamespace(
            agent_run=run,
            user_message=user_message,
            assistant_message=assistant_message,
            action_requests=(),
        ),
    )
    graph = CapturingGraph()

    result = await _runtime(service, graph).run_turn(
        _trusted_context(),
        conversation_id,
        "hello",
        interaction_mode=InteractionMode.VOICE,
        voice_session_id=run.voice_session_id,
        voice_turn_id=run.voice_turn_id,
    )

    assert result.agent_run_id == run_id
    assert result.assistant_message_id == assistant_message.id
    assert result.content == "durable"
    assert graph.context is None
    assert service.start_calls == []


@pytest.mark.asyncio
async def test_failed_voice_turn_replay_exposes_only_recorded_bounded_error() -> None:
    conversation_id = uuid4()
    user_message = MessageRecord(uuid4(), conversation_id, 1, "user", "hello", NOW)
    run = AgentRunRecord(
        uuid4(),
        conversation_id,
        user_message.id,
        None,
        "failed",
        "graph-v1",
        "prompt-v1",
        "tools-v1",
        NOW,
        NOW,
        "agent_unavailable",
        InteractionMode.VOICE,
        uuid4(),
        uuid4(),
    )
    service = ReplayConversationService(
        [],
        [],
        replay=SimpleNamespace(
            agent_run=run,
            user_message=user_message,
            assistant_message=None,
            action_requests=(),
        ),
    )

    with pytest.raises(AgentVoiceTurnFailedError) as error:
        await _runtime(service, CapturingGraph()).run_turn(
            _trusted_context(),
            conversation_id,
            "hello",
            interaction_mode=InteractionMode.VOICE,
            voice_session_id=run.voice_session_id,
            voice_turn_id=run.voice_turn_id,
        )

    assert error.value.recorded_error_code == "agent_unavailable"
