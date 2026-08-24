"""M3B durable conversation and trace persistence contract tests."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from verbaops.conversations.domain import ConversationRecord, ConversationScope
from verbaops.conversations.errors import ConversationBusyError, ConversationNotFoundError
from verbaops.conversations.service import ConversationService
from verbaops.llm.models import CapabilityAlias, ResponseMetadata

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.m3b,
    pytest.mark.usefixtures("clean_verbaops_tables"),
]

TENANT = UUID("10000000-0000-0000-0000-000000000001")
PRINCIPAL = UUID("20000000-0000-0000-0000-000000000001")
OTHER_TENANT = UUID("10000000-0000-0000-0000-000000000002")
OTHER_PRINCIPAL = UUID("20000000-0000-0000-0000-000000000002")
SCOPE = ConversationScope(tenant_id=TENANT, principal_id=PRINCIPAL)
OTHER_SCOPE = ConversationScope(tenant_id=OTHER_TENANT, principal_id=OTHER_PRINCIPAL)


async def create_conversation(
    service: ConversationService, scope: ConversationScope = SCOPE
) -> ConversationRecord:
    return await service.create_conversation(scope)


@pytest.mark.asyncio
async def test_m3b_tables_indexes_and_partial_running_index_exist(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        tables = await connection.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name IN "
                "('conversations', 'messages', 'agent_runs', 'model_calls', 'tool_invocations') "
                "ORDER BY table_name"
            )
        )
        indexes = await connection.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname = 'public' AND tablename IN "
                "('conversations', 'agent_runs', 'messages', 'model_calls', 'tool_invocations')"
            )
        )
    assert [row[0] for row in tables] == [
        "agent_runs",
        "conversations",
        "messages",
        "model_calls",
        "tool_invocations",
    ]
    index_definitions = {row[0]: row[1] for row in indexes}
    assert "ix_conversations_tenant_principal_updated" in index_definitions
    assert "uq_agent_runs_one_running_per_conversation" in index_definitions
    assert (
        "WHERE ((status)::text = 'running'::text)"
        in index_definitions["uq_agent_runs_one_running_per_conversation"]
    )


@pytest.mark.asyncio
async def test_scope_isolation_and_foreign_nonexistent_not_found_are_identical(
    service: ConversationService,
) -> None:
    conversation = await create_conversation(service)

    with pytest.raises(ConversationNotFoundError) as foreign_error:
        await service.get_conversation(OTHER_SCOPE, conversation.id)
    with pytest.raises(ConversationNotFoundError) as missing_error:
        await service.get_conversation(SCOPE, uuid4())

    assert str(foreign_error.value) == str(missing_error.value)
    with pytest.raises(ConversationNotFoundError):
        await service.list_messages(OTHER_SCOPE, conversation.id)


@pytest.mark.asyncio
async def test_turn_start_commits_user_message_and_running_run(
    service: ConversationService,
) -> None:
    conversation = await create_conversation(service)
    started = await service.start_turn(
        SCOPE,
        conversation.id,
        "Where is my order?",
        graph_version="graph-v1",
        prompt_version="prompt-v1",
        tool_schema_version="tools-v1",
    )

    assert started.user_message.sequence == 1
    assert started.user_message.role == "user"
    assert started.agent_run.status == "running"
    assert started.agent_run.user_message_id == started.user_message.id
    assert started.agent_run.started_at.tzinfo is not None


@pytest.mark.asyncio
async def test_complete_and_failed_runs_allow_following_turns(service: ConversationService) -> None:
    conversation = await create_conversation(service)
    first = await service.start_turn(
        SCOPE,
        conversation.id,
        "First",
        graph_version="g",
        prompt_version="p",
        tool_schema_version="t",
    )
    completed = await service.complete_turn(SCOPE, conversation.id, first.agent_run.id, "Done")
    assert completed.assistant_message.sequence == 2
    assert completed.agent_run.status == "completed"
    assert completed.agent_run.completed_at is not None

    second = await service.start_turn(
        SCOPE,
        conversation.id,
        "Second",
        graph_version="g",
        prompt_version="p",
        tool_schema_version="t",
    )
    await service.fail_turn(SCOPE, conversation.id, second.agent_run.id, "gateway_unavailable")
    third = await service.start_turn(
        SCOPE,
        conversation.id,
        "Third",
        graph_version="g",
        prompt_version="p",
        tool_schema_version="t",
    )
    assert third.agent_run.status == "running"


@pytest.mark.asyncio
async def test_model_call_metadata_uses_m3a_field_names_and_nullable_values(
    service: ConversationService, engine: AsyncEngine
) -> None:
    conversation = await create_conversation(service)
    started = await service.start_turn(
        SCOPE,
        conversation.id,
        "Trace this",
        graph_version="g",
        prompt_version="p",
        tool_schema_version="t",
    )
    metadata = ResponseMetadata(
        capability_alias=CapabilityAlias.AGENT_FAST,
        gateway_request_id="call-123",
        gateway_model_id="deployment-456",
        model="provider/model-name",
        provider="openai",
        input_tokens=10,
        output_tokens=7,
        total_tokens=17,
        latency_ms=123.4,
        cost_usd=0.001,
        finish_reason="stop",
    )
    model_call = await service.append_model_call(
        SCOPE, conversation.id, started.agent_run.id, metadata
    )
    assert model_call.sequence == 1
    assert model_call.gateway_model_id == "deployment-456"
    assert model_call.model == "provider/model-name"
    assert model_call.total_tokens == 17

    async with engine.connect() as connection:
        row = await connection.execute(
            text(
                "SELECT capability_alias, gateway_request_id, gateway_model_id, model, provider, "
                "input_tokens, output_tokens, total_tokens, latency_ms, cost_usd, finish_reason "
                "FROM model_calls WHERE id = :id"
            ),
            {"id": model_call.id},
        )
    assert row.one() == (
        "agent-fast",
        "call-123",
        "deployment-456",
        "provider/model-name",
        "openai",
        10,
        7,
        17,
        123.4,
        0.001,
        "stop",
    )


@pytest.mark.asyncio
async def test_tool_invocation_jsonb_round_trip_and_sequence(service: ConversationService) -> None:
    conversation = await create_conversation(service)
    started = await service.start_turn(
        SCOPE,
        conversation.id,
        "Use a tool",
        graph_version="g",
        prompt_version="p",
        tool_schema_version="t",
    )
    invocation = await service.append_tool_invocation(
        SCOPE,
        conversation.id,
        started.agent_run.id,
        tool_call_id="call-1",
        tool_name="lookup_order",
        risk_level="read",
        arguments={"order_id": "order-1", "nested": {"safe": True}},
    )
    assert invocation.sequence == 1
    assert invocation.arguments_json == {"order_id": "order-1", "nested": {"safe": True}}


@pytest.mark.asyncio
async def test_stale_running_run_is_failed_before_new_turn(
    service: ConversationService, engine: AsyncEngine
) -> None:
    conversation = await create_conversation(service)
    started = await service.start_turn(
        SCOPE,
        conversation.id,
        "Stale",
        graph_version="g",
        prompt_version="p",
        tool_schema_version="t",
    )
    old = datetime.now(UTC) - timedelta(minutes=31)
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE agent_runs SET started_at = :started_at WHERE id = :id"),
            {"started_at": old, "id": started.agent_run.id},
        )

    replacement = await service.start_turn(
        SCOPE,
        conversation.id,
        "Replacement",
        graph_version="g",
        prompt_version="p",
        tool_schema_version="t",
    )
    assert replacement.agent_run.status == "running"
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text("SELECT status, error_code FROM agent_runs WHERE id = :id"),
                {"id": started.agent_run.id},
            )
        ).one()
    assert row == ("failed", "stale_run_recovered")


@pytest.mark.asyncio
async def test_database_constraints_cover_sequences_roles_status_and_nonnegative_values(
    service: ConversationService, engine: AsyncEngine
) -> None:
    conversation = await create_conversation(service)
    started = await service.start_turn(
        SCOPE,
        conversation.id,
        "Valid",
        graph_version="g",
        prompt_version="p",
        tool_schema_version="t",
    )
    statements = [
        (
            "INSERT INTO messages (id, conversation_id, sequence, role, content, created_at) "
            "VALUES (:id, :conversation_id, 0, 'user', 'bad', now())",
            {"id": uuid4(), "conversation_id": conversation.id},
        ),
        (
            "INSERT INTO messages (id, conversation_id, sequence, role, content, created_at) "
            "VALUES (:id, :conversation_id, 2, 'system', 'bad', now())",
            {"id": uuid4(), "conversation_id": conversation.id},
        ),
        (
            "INSERT INTO agent_runs (id, conversation_id, user_message_id, status, graph_version, "
            "prompt_version, tool_schema_version, started_at) VALUES (:id, :conversation_id, "
            ":user_message_id, 'running', 'g', 'p', 't', now())",
            {
                "id": uuid4(),
                "conversation_id": conversation.id,
                "user_message_id": started.user_message.id,
            },
        ),
    ]
    for statement, params in statements:
        with pytest.raises(IntegrityError):
            async with engine.begin() as connection:
                await connection.execute(text(statement), params)

    metadata = ResponseMetadata(capability_alias=CapabilityAlias.AGENT_FAST)
    await service.append_model_call(SCOPE, conversation.id, started.agent_run.id, metadata)
    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO model_calls (id, agent_run_id, sequence, capability_alias, "
                    "input_tokens, status, created_at) VALUES (:id, :run_id, 2, 'agent-fast', "
                    "-1, 'succeeded', now())"
                ),
                {"id": uuid4(), "run_id": uuid4()},
            )


@pytest.mark.asyncio
async def test_start_and_completion_rollback_atomically(
    service: ConversationService, engine: AsyncEngine
) -> None:
    conversation = await create_conversation(service)
    with pytest.raises(IntegrityError):
        await service.start_turn(
            SCOPE,
            conversation.id,
            "Will roll back",
            graph_version="",
            prompt_version="p",
            tool_schema_version="t",
        )
    async with engine.connect() as connection:
        assert (
            await connection.execute(
                text("SELECT count(*) FROM messages WHERE conversation_id = :id"),
                {"id": conversation.id},
            )
        ).scalar_one() == 0

    started = await service.start_turn(
        SCOPE,
        conversation.id,
        "Complete atomically",
        graph_version="g",
        prompt_version="p",
        tool_schema_version="t",
    )
    with pytest.raises(IntegrityError):
        await service.complete_turn(SCOPE, conversation.id, started.agent_run.id, "")
    async with engine.connect() as connection:
        status, count = (
            await connection.execute(
                text(
                    "SELECT agent_runs.status, count(messages.id) FROM agent_runs "
                    "LEFT JOIN messages ON messages.conversation_id = agent_runs.conversation_id "
                    "WHERE agent_runs.id = :id GROUP BY agent_runs.status"
                ),
                {"id": started.agent_run.id},
            )
        ).one()
    assert status == "running"
    assert count == 1


@pytest.mark.asyncio
async def test_foreign_keys_reject_orphan_trace_rows(
    service: ConversationService, engine: AsyncEngine
) -> None:
    conversation = await create_conversation(service)
    await service.start_turn(
        SCOPE,
        conversation.id,
        "Parent",
        graph_version="g",
        prompt_version="p",
        tool_schema_version="t",
    )
    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO model_calls (id, agent_run_id, sequence, capability_alias, status, created_at) "
                    "VALUES (:id, :run_id, 1, 'agent-fast', 'succeeded', now())"
                ),
                {"id": uuid4(), "run_id": uuid4()},
            )
    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO tool_invocations (id, agent_run_id, sequence, tool_call_id, tool_name, "
                    "risk_level, arguments_json, status, created_at) VALUES (:id, :run_id, 1, 'call', "
                    "'tool', 'read', '{}', 'proposed', now())"
                ),
                {"id": uuid4(), "run_id": uuid4()},
            )


@pytest.mark.asyncio
async def test_database_uses_only_customer_visible_user_and_assistant_messages(
    service: ConversationService, engine: AsyncEngine
) -> None:
    conversation = await create_conversation(service)
    started = await service.start_turn(
        SCOPE,
        conversation.id,
        "Visible user",
        graph_version="g",
        prompt_version="p",
        tool_schema_version="t",
    )
    await service.append_tool_invocation(
        SCOPE,
        conversation.id,
        started.agent_run.id,
        tool_call_id="call",
        tool_name="read_only",
        risk_level="read",
        arguments={},
    )
    await service.complete_turn(SCOPE, conversation.id, started.agent_run.id, "Visible assistant")
    messages = await service.list_messages(SCOPE, conversation.id)
    assert [(message.role, message.content) for message in messages] == [
        ("user", "Visible user"),
        ("assistant", "Visible assistant"),
    ]
    async with engine.connect() as connection:
        assert (
            await connection.execute(
                text("SELECT count(*) FROM messages WHERE conversation_id = :id"),
                {"id": conversation.id},
            )
        ).scalar_one() == 2


@pytest.mark.asyncio
async def test_metadata_can_be_entirely_nullable_except_capability_alias(
    service: ConversationService,
) -> None:
    conversation = await create_conversation(service)
    started = await service.start_turn(
        SCOPE,
        conversation.id,
        "Nullable metadata",
        graph_version="g",
        prompt_version="p",
        tool_schema_version="t",
    )
    model_call = await service.append_model_call(
        SCOPE,
        conversation.id,
        started.agent_run.id,
        ResponseMetadata(capability_alias=CapabilityAlias.AGENT_FAST),
    )
    assert model_call.gateway_request_id is None
    assert model_call.gateway_model_id is None
    assert model_call.model is None
    assert model_call.provider is None
    assert model_call.cost_usd is None


@pytest.mark.asyncio
async def test_sequence_constraints_reject_duplicate_model_and_tool_sequences(
    service: ConversationService, engine: AsyncEngine
) -> None:
    conversation = await create_conversation(service)
    started = await service.start_turn(
        SCOPE,
        conversation.id,
        "Duplicate sequences",
        graph_version="g",
        prompt_version="p",
        tool_schema_version="t",
    )
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO model_calls (id, agent_run_id, sequence, capability_alias, status, created_at) "
                "VALUES (:id, :run_id, 1, 'agent-fast', 'succeeded', now())"
            ),
            {"id": uuid4(), "run_id": started.agent_run.id},
        )
    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO model_calls (id, agent_run_id, sequence, capability_alias, status, created_at) "
                    "VALUES (:id, :run_id, 1, 'agent-fast', 'failed', now())"
                ),
                {"id": uuid4(), "run_id": started.agent_run.id},
            )
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO tool_invocations (id, agent_run_id, sequence, tool_call_id, tool_name, "
                "risk_level, arguments_json, status, created_at) VALUES (:id, :run_id, 1, 'call-1', "
                "'tool', 'read', '{}', 'proposed', now())"
            ),
            {"id": uuid4(), "run_id": started.agent_run.id},
        )
    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO tool_invocations (id, agent_run_id, sequence, tool_call_id, tool_name, "
                    "risk_level, arguments_json, status, created_at) VALUES (:id, :run_id, 1, 'call-2', "
                    "'tool', 'read', '{}', 'proposed', now())"
                ),
                {"id": uuid4(), "run_id": started.agent_run.id},
            )


@pytest.mark.asyncio
async def test_conversation_busy_is_typed_and_does_not_expose_unsafe_lookup(
    service: ConversationService,
) -> None:
    conversation = await create_conversation(service)
    await service.start_turn(
        SCOPE,
        conversation.id,
        "Already running",
        graph_version="g",
        prompt_version="p",
        tool_schema_version="t",
    )
    with pytest.raises(ConversationBusyError):
        await service.start_turn(
            SCOPE,
            conversation.id,
            "Second turn",
            graph_version="g",
            prompt_version="p",
            tool_schema_version="t",
        )
    assert not hasattr(service, "get_conversation_by_id")
