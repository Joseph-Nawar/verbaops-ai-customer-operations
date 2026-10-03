"""PostgreSQL fixtures shared by Stage 6 action contract tests."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from verbaops.auth.context import Role, TrustedContext


@dataclass(frozen=True)
class Stage6ActionContext:
    trusted_context: TrustedContext
    conversation_id: UUID
    agent_run_id: UUID
    tool_invocation_ids: tuple[UUID, ...]


async def seed_stage6_action_context(
    postgres_engine: AsyncEngine, *, tool_invocation_count: int = 2
) -> Stage6ActionContext:
    now = datetime.now(UTC)
    tenant_id = uuid4()
    customer_id = uuid4()
    principal_id = uuid4()
    conversation_id = uuid4()
    message_id = uuid4()
    agent_run_id = uuid4()
    tool_invocation_ids = tuple(uuid4() for _ in range(tool_invocation_count))

    async with postgres_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO conversations "
                "(id, tenant_id, principal_id, customer_id, created_at, updated_at) "
                "VALUES (:id, :tenant_id, :principal_id, :customer_id, :created_at, :updated_at)"
            ),
            {
                "id": conversation_id,
                "tenant_id": tenant_id,
                "principal_id": principal_id,
                "customer_id": customer_id,
                "created_at": now,
                "updated_at": now,
            },
        )
        await connection.execute(
            text(
                "INSERT INTO messages (id, conversation_id, sequence, role, content, created_at) "
                "VALUES (:id, :conversation_id, 1, 'user', 'test action proposal', :created_at)"
            ),
            {"id": message_id, "conversation_id": conversation_id, "created_at": now},
        )
        await connection.execute(
            text(
                "INSERT INTO agent_runs "
                "(id, conversation_id, user_message_id, status, graph_version, prompt_version, "
                "tool_schema_version, started_at) "
                "VALUES (:id, :conversation_id, :message_id, 'completed', 'g1', 'p1', 't1', :started_at)"
            ),
            {
                "id": agent_run_id,
                "conversation_id": conversation_id,
                "message_id": message_id,
                "started_at": now,
            },
        )
        for sequence, tool_invocation_id in enumerate(tool_invocation_ids, start=1):
            await connection.execute(
                text(
                    "INSERT INTO tool_invocations "
                    "(id, agent_run_id, sequence, tool_call_id, tool_name, risk_level, "
                    "arguments_json, status, created_at, completed_at) "
                    "VALUES (:id, :agent_run_id, :sequence, :tool_call_id, "
                    "'propose_cancel_order', 'write', CAST(:arguments AS jsonb), 'succeeded', "
                    ":created_at, :completed_at)"
                ),
                {
                    "id": tool_invocation_id,
                    "agent_run_id": agent_run_id,
                    "sequence": sequence,
                    "tool_call_id": f"stage6-{tool_invocation_id}",
                    "arguments": "{}",
                    "created_at": now,
                    "completed_at": now,
                },
            )

    return Stage6ActionContext(
        trusted_context=TrustedContext(
            principal_id=principal_id,
            tenant_id=tenant_id,
            customer_id=customer_id,
            roles=frozenset({Role.CUSTOMER}),
        ),
        conversation_id=conversation_id,
        agent_run_id=agent_run_id,
        tool_invocation_ids=tool_invocation_ids,
    )


@pytest_asyncio.fixture
async def clean_stage6_action_tables(postgres_engine: AsyncEngine) -> AsyncIterator[None]:
    async with postgres_engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE action_events, action_requests"))
    yield
