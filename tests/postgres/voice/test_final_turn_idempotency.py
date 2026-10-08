"""PostgreSQL contracts for durable FINAL voice-turn idempotency."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from verbaops.actions.models import ActionRequestSummary, ActionState, ActionType
from verbaops.conversations.domain import ConversationScope
from verbaops.conversations.errors import ConversationBusyError
from verbaops.conversations.service import ConversationService
from verbaops.voice.domain import VoiceSessionState
from verbaops.voice.repository import VoiceSessionRepository
from verbaops.voice.service import VoiceSessionService

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.contract]


async def _seed(
    engine: AsyncEngine,
) -> tuple[ConversationService, ConversationScope, UUID, UUID, UUID]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    service = ConversationService(factory)
    scope = ConversationScope(uuid4(), uuid4())
    customer_id = uuid4()
    conversation = await service.create_conversation(scope, customer_id=customer_id)
    async with factory() as session, session.begin():
        voice_session = await VoiceSessionRepository(session).create_session(
            tenant_id=scope.tenant_id,
            principal_id=scope.principal_id,
            customer_id=customer_id,
            conversation_id=conversation.id,
            transport_provider="livekit",
            stt_provider="stt",
            tts_provider="tts",
            room_identity=f"room-{uuid4()}",
            participant_identity=f"participant-{uuid4()}",
            status=VoiceSessionState.CREATED,
            created_at=datetime.now(UTC),
        )
    lifecycle = VoiceSessionService(factory)
    await lifecycle.mark_connecting(voice_session.id)
    await lifecycle.mark_connected(voice_session.id)
    return service, scope, customer_id, conversation.id, voice_session.id


def _summary() -> ActionRequestSummary:
    return ActionRequestSummary(
        action_request_id=uuid4(),
        action_type=ActionType.CANCEL_ORDER,
        state=ActionState.AWAITING_CONFIRMATION,
        proposal_fingerprint="a" * 64,
        safe_summary="Cancel the order.",
        required_next_actor="customer",
        reason_code="allowed",
    )


@pytest.mark.asyncio
async def test_final_voice_turn_replays_completed_and_failed_durable_state(
    postgres_engine: AsyncEngine,
) -> None:
    service, scope, customer_id, conversation_id, voice_session_id = await _seed(postgres_engine)
    first_turn_id = uuid4()
    first = await service.start_voice_turn(
        scope,
        conversation_id,
        "cancel my order",
        graph_version="graph-v1",
        prompt_version="prompt-v1",
        tool_schema_version="tools-v1",
        voice_session_id=voice_session_id,
        voice_turn_id=first_turn_id,
        customer_id=customer_id,
    )
    assert first.turn_start is not None
    running_duplicate = await service.start_voice_turn(
        scope,
        conversation_id,
        "cancel my order",
        graph_version="graph-v1",
        prompt_version="prompt-v1",
        tool_schema_version="tools-v1",
        voice_session_id=voice_session_id,
        voice_turn_id=first_turn_id,
        customer_id=customer_id,
    )
    assert running_duplicate.replay is not None
    assert running_duplicate.replay.agent_run.status == "running"
    run_id = first.turn_start.agent_run.id
    summary = _summary()
    await service.append_tool_invocation(
        scope,
        conversation_id,
        run_id,
        tool_call_id="proposal-1",
        tool_name="propose_cancel_order",
        risk_level="proposal",
        arguments={"order_id": str(uuid4())},
        status="succeeded",
        result=summary.model_dump(mode="json"),
        latency_ms=1.0,
        completed_at=datetime.now(UTC),
    )
    completed = await service.complete_turn(scope, conversation_id, run_id, "Please confirm.")
    replay = await service.start_voice_turn(
        scope,
        conversation_id,
        "cancel my order",
        graph_version="graph-v1",
        prompt_version="prompt-v1",
        tool_schema_version="tools-v1",
        voice_session_id=voice_session_id,
        voice_turn_id=first_turn_id,
        customer_id=customer_id,
    )
    assert replay.replay is not None
    assert replay.replay.agent_run.id == run_id
    assert replay.replay.assistant_message is not None
    assert replay.replay.assistant_message.id == completed.assistant_message.id
    assert replay.replay.assistant_message.content == "Please confirm."
    assert replay.replay.agent_run.started_at == first.turn_start.agent_run.started_at
    assert replay.replay.action_requests == (summary,)

    failed_turn_id = uuid4()
    failed = await service.start_voice_turn(
        scope,
        conversation_id,
        "try again",
        graph_version="graph-v1",
        prompt_version="prompt-v1",
        tool_schema_version="tools-v1",
        voice_session_id=voice_session_id,
        voice_turn_id=failed_turn_id,
        customer_id=customer_id,
    )
    assert failed.turn_start is not None
    await service.fail_turn(
        scope,
        conversation_id,
        failed.turn_start.agent_run.id,
        "agent_unavailable",
    )
    failed_replay = await service.start_voice_turn(
        scope,
        conversation_id,
        "try again",
        graph_version="graph-v1",
        prompt_version="prompt-v1",
        tool_schema_version="tools-v1",
        voice_session_id=voice_session_id,
        voice_turn_id=failed_turn_id,
        customer_id=customer_id,
    )
    assert failed_replay.replay is not None
    assert failed_replay.replay.agent_run.status == "failed"
    assert failed_replay.replay.agent_run.error_code == "agent_unavailable"

    async with postgres_engine.connect() as connection:
        counts = (
            await connection.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM messages WHERE conversation_id = :conversation_id), "
                    "(SELECT count(*) FROM agent_runs WHERE conversation_id = :conversation_id)"
                ),
                {"conversation_id": conversation_id},
            )
        ).one()
    assert counts == (3, 2)


@pytest.mark.asyncio
async def test_same_final_voice_turn_concurrency_has_one_durable_winner(
    postgres_engine: AsyncEngine,
) -> None:
    service, scope, customer_id, conversation_id, voice_session_id = await _seed(postgres_engine)
    turn_id = uuid4()

    async def submit() -> object:
        return await service.start_voice_turn(
            scope,
            conversation_id,
            "hello",
            graph_version="graph-v1",
            prompt_version="prompt-v1",
            tool_schema_version="tools-v1",
            voice_session_id=voice_session_id,
            voice_turn_id=turn_id,
            customer_id=customer_id,
        )

    first, second = await asyncio.gather(submit(), submit())
    claims = [first, second]
    assert sum(claim.turn_start is not None for claim in claims) == 1
    assert sum(claim.replay is not None for claim in claims) == 1
    async with postgres_engine.connect() as connection:
        counts = (
            await connection.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM messages WHERE conversation_id = :conversation_id), "
                    "(SELECT count(*) FROM agent_runs WHERE conversation_id = :conversation_id)"
                ),
                {"conversation_id": conversation_id},
            )
        ).one()
    assert counts == (1, 1)


@pytest.mark.asyncio
async def test_different_voice_turn_keeps_one_running_conversation_busy(
    postgres_engine: AsyncEngine,
) -> None:
    service, scope, customer_id, conversation_id, voice_session_id = await _seed(postgres_engine)
    first = await service.start_voice_turn(
        scope,
        conversation_id,
        "first",
        graph_version="graph-v1",
        prompt_version="prompt-v1",
        tool_schema_version="tools-v1",
        voice_session_id=voice_session_id,
        voice_turn_id=uuid4(),
        customer_id=customer_id,
    )
    assert first.turn_start is not None
    with pytest.raises(ConversationBusyError):
        await service.start_voice_turn(
            scope,
            conversation_id,
            "second",
            graph_version="graph-v1",
            prompt_version="prompt-v1",
            tool_schema_version="tools-v1",
            voice_session_id=voice_session_id,
            voice_turn_id=uuid4(),
            customer_id=customer_id,
        )
