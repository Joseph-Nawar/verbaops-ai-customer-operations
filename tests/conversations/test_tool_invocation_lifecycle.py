"""M6C PostgreSQL tests for durable tool origin creation and finalization."""

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from verbaops.conversations.domain import ConversationScope
from verbaops.conversations.errors import ConversationNotFoundError
from verbaops.conversations.service import ConversationService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.m3b,
    pytest.mark.usefixtures("clean_verbaops_tables"),
]

SCOPE = ConversationScope(
    tenant_id=UUID("50000000-0000-0000-0000-000000000001"),
    principal_id=UUID("60000000-0000-0000-0000-000000000001"),
)
OTHER_SCOPE = ConversationScope(
    tenant_id=UUID("50000000-0000-0000-0000-000000000002"),
    principal_id=UUID("60000000-0000-0000-0000-000000000002"),
)


async def _running_turn(service: ConversationService) -> tuple[Any, Any]:
    conversation = await service.create_conversation(SCOPE)
    turn = await service.start_turn(
        SCOPE,
        conversation.id,
        "Please check this.",
        graph_version="g",
        prompt_version="p",
        tool_schema_version="t",
    )
    return conversation, turn


@pytest.mark.asyncio
async def test_invocation_is_committed_as_proposed_then_same_scoped_row_is_finalized(
    service: ConversationService,
    engine: AsyncEngine,
) -> None:
    conversation, turn = await _running_turn(service)
    invocation = await service.begin_tool_invocation(
        SCOPE,
        conversation.id,
        turn.agent_run.id,
        tool_call_id="provider-call-1",
        tool_name="get_order_status",
        risk_level="read_only",
        arguments={"order_id": str(uuid4())},
    )

    assert invocation.status == "proposed"
    assert invocation.created_at is not None
    assert invocation.id != UUID(int=0)

    with pytest.raises(ConversationNotFoundError):
        await service.complete_tool_invocation(
            OTHER_SCOPE,
            conversation.id,
            turn.agent_run.id,
            invocation.id,
            status="succeeded",
            result={"status": "ok"},
            latency_ms=1.0,
        )
    with pytest.raises(ConversationNotFoundError):
        await service.complete_tool_invocation(
            SCOPE,
            uuid4(),
            turn.agent_run.id,
            invocation.id,
            status="succeeded",
            result={"status": "ok"},
            latency_ms=1.0,
        )
    other_conversation, other_turn = await _running_turn(service)
    with pytest.raises(ConversationNotFoundError):
        await service.complete_tool_invocation(
            SCOPE,
            other_conversation.id,
            other_turn.agent_run.id,
            invocation.id,
            status="succeeded",
            result={"status": "ok"},
            latency_ms=1.0,
        )
    with pytest.raises(ConversationNotFoundError):
        await service.complete_tool_invocation(
            SCOPE,
            conversation.id,
            turn.agent_run.id,
            uuid4(),
            status="succeeded",
            result={"status": "ok"},
            latency_ms=1.0,
        )

    completed = await service.complete_tool_invocation(
        SCOPE,
        conversation.id,
        turn.agent_run.id,
        invocation.id,
        status="succeeded",
        result={"status": "safe"},
        latency_ms=12.5,
    )

    assert completed.id == invocation.id
    assert completed.status == "succeeded"
    assert completed.result_json == {"status": "safe"}
    assert completed.latency_ms == 12.5
    assert completed.completed_at is not None
    async with engine.connect() as connection:
        count = await connection.scalar(
            text("SELECT count(*) FROM tool_invocations WHERE agent_run_id = :run_id"),
            {"run_id": turn.agent_run.id},
        )
    assert count == 1


@pytest.mark.asyncio
async def test_duplicate_provider_call_ids_are_trace_metadata_not_unique_identity(
    service: ConversationService,
    engine: AsyncEngine,
) -> None:
    conversation, turn = await _running_turn(service)

    async def begin() -> Any:
        return await service.begin_tool_invocation(
            SCOPE,
            conversation.id,
            turn.agent_run.id,
            tool_call_id="reused-provider-id",
            tool_name="get_order_status",
            risk_level="read_only",
            arguments={"order_id": str(uuid4())},
        )

    first, second = await asyncio.gather(begin(), begin())

    assert first.id != second.id
    assert {first.sequence, second.sequence} == {1, 2}
    async with engine.connect() as connection:
        index_definitions = await connection.scalars(
            text("SELECT indexdef FROM pg_indexes WHERE tablename = 'tool_invocations'")
        )
    assert not any(
        "UNIQUE" in index_definition.upper() and "TOOL_CALL_ID" in index_definition.upper()
        for index_definition in index_definitions
    )


@pytest.mark.asyncio
@pytest.mark.concurrency
async def test_failure_finalizes_the_same_durable_invocation(service: ConversationService) -> None:
    conversation, turn = await _running_turn(service)
    invocation = await service.begin_tool_invocation(
        SCOPE,
        conversation.id,
        turn.agent_run.id,
        tool_call_id="provider-call-failed",
        tool_name="get_order_status",
        risk_level="read_only",
        arguments={"order_id": str(uuid4())},
    )

    failed = await service.complete_tool_invocation(
        SCOPE,
        conversation.id,
        turn.agent_run.id,
        invocation.id,
        status="failed",
        result={"status": "unavailable"},
        latency_ms=4.0,
        error_code="commerce_unavailable",
    )

    assert failed.id == invocation.id
    assert failed.status == "failed"
    assert failed.error_code == "commerce_unavailable"
