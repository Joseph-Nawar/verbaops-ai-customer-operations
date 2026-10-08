"""PostgreSQL contracts for the M7A voice-session and provenance schema."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.contract]


async def _seed_conversation(engine: AsyncEngine) -> tuple[dict[str, object], dict[str, object]]:
    now = datetime.now(UTC)
    values = {
        "tenant_id": uuid4(),
        "principal_id": uuid4(),
        "customer_id": uuid4(),
        "conversation_id": uuid4(),
        "message_id": uuid4(),
        "agent_run_id": uuid4(),
        "voice_session_id": uuid4(),
        "voice_turn_id": uuid4(),
        "now": now,
    }
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO conversations "
                "(id, tenant_id, principal_id, customer_id, created_at, updated_at) "
                "VALUES (:conversation_id, :tenant_id, :principal_id, :customer_id, :now, :now)"
            ),
            values,
        )
    return values, {"now": now}


@pytest.mark.asyncio
async def test_voice_session_schema_has_exact_security_sensitive_shape(
    postgres_engine: AsyncEngine,
) -> None:
    async with postgres_engine.connect() as connection:
        columns = await connection.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'voice_sessions'"
            )
        )
        constraints = await connection.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE connamespace = 'public'::regnamespace "
                "AND (conrelid = 'voice_sessions'::regclass OR conrelid = 'agent_runs'::regclass)"
            )
        )
        indexes = await connection.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname = 'public' AND tablename IN ('voice_sessions', 'agent_runs')"
            )
        )

    actual_columns = set(columns.scalars())
    assert actual_columns == {
        "id",
        "tenant_id",
        "principal_id",
        "customer_id",
        "conversation_id",
        "transport_provider",
        "stt_provider",
        "tts_provider",
        "room_identity",
        "participant_identity",
        "status",
        "created_at",
        "connected_at",
        "ended_at",
        "error_code",
    }
    check_names = set(constraints.scalars())
    assert {
        "voice_session_status_allowed",
        "voice_session_connected_timestamp_consistent",
        "voice_session_ended_timestamp_consistent",
        "agent_run_interaction_mode_allowed",
        "agent_run_provenance_consistent",
    } <= check_names
    index_map = {str(name): str(definition) for name, definition in indexes}
    assert "uq_agent_runs_one_running_per_conversation" in index_map
    assert "uq_agent_runs_voice_session_turn" in index_map
    assert "voice_session_id" in index_map["uq_agent_runs_voice_session_turn"]
    assert "voice_turn_id" in index_map["uq_agent_runs_voice_session_turn"]


@pytest.mark.asyncio
async def test_voice_session_identity_and_provenance_constraints_reject_invalid_rows(
    postgres_engine: AsyncEngine,
) -> None:
    values, _ = await _seed_conversation(postgres_engine)
    async with postgres_engine.connect() as connection, connection.begin():
        with pytest.raises(DBAPIError):
            async with connection.begin_nested():
                await connection.execute(
                    text(
                        "INSERT INTO voice_sessions "
                        "(id, tenant_id, principal_id, customer_id, conversation_id, "
                        "transport_provider, stt_provider, tts_provider, room_identity, "
                        "participant_identity, status, created_at) VALUES "
                        "(:id, :tenant_id, :principal_id, :customer_id, :conversation_id, "
                        "'not-livekit', 'stt', 'tts', 'room', 'participant', 'created', :now)"
                    ),
                    {**values, "id": uuid4()},
                )

        with pytest.raises(DBAPIError):
            async with connection.begin_nested():
                await connection.execute(
                    text(
                        "INSERT INTO agent_runs "
                        "(id, conversation_id, user_message_id, status, graph_version, "
                        "prompt_version, tool_schema_version, interaction_mode, voice_session_id, "
                        "voice_turn_id, started_at) VALUES "
                        "(:id, :conversation_id, :message_id, 'completed', 'g', 'p', 't', "
                        "'voice', NULL, NULL, :now)"
                    ),
                    {**values, "id": uuid4()},
                )


@pytest.mark.asyncio
async def test_voice_provenance_is_unique_and_text_defaults_remain_valid(
    postgres_engine: AsyncEngine,
) -> None:
    values, _ = await _seed_conversation(postgres_engine)
    async with postgres_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO messages (id, conversation_id, sequence, role, content, created_at) "
                "VALUES (:message_id, :conversation_id, 1, 'user', 'text', :now)"
            ),
            values,
        )
        await connection.execute(
            text(
                "INSERT INTO agent_runs "
                "(id, conversation_id, user_message_id, status, graph_version, prompt_version, "
                "tool_schema_version, started_at) VALUES "
                "(:id, :conversation_id, :message_id, 'completed', 'g', 'p', 't', :now)"
            ),
            {**values, "id": values["agent_run_id"]},
        )
        await connection.execute(
            text(
                "INSERT INTO voice_sessions "
                "(id, tenant_id, principal_id, customer_id, conversation_id, transport_provider, "
                "stt_provider, tts_provider, room_identity, participant_identity, status, created_at) "
                "VALUES (:voice_session_id, :tenant_id, :principal_id, :customer_id, "
                ":conversation_id, 'livekit', 'stt', 'tts', 'room', 'participant', 'created', :now)"
            ),
            values,
        )
        await connection.execute(
            text(
                "INSERT INTO messages (id, conversation_id, sequence, role, content, created_at) "
                "VALUES (:id, :conversation_id, 2, 'user', 'voice', :now)"
            ),
            {**values, "id": uuid4()},
        )
