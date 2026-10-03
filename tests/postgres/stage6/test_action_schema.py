"""PostgreSQL contracts for the M6A action lifecycle schema."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from tests.postgres.stage6.conftest import Stage6ActionContext, seed_stage6_action_context

from verbaops.actions.models import CancelOrderProposal
from verbaops.actions.repository import ActionRepository
from verbaops.actions.transitions import ActionRequestRecord

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.contract]

EXPECTED_COLUMNS = {
    "action_requests": {
        "id",
        "tenant_id",
        "customer_id",
        "proposing_principal_id",
        "conversation_id",
        "agent_run_id",
        "originating_tool_invocation_id",
        "action_type",
        "proposal_payload",
        "target_ids",
        "proposal_schema_version",
        "proposal_fingerprint",
        "state",
        "policy_allowed",
        "policy_reason_code",
        "policy_version",
        "policy_observed_at",
        "confirmation_required",
        "approval_required",
        "customer_confirmation_decision",
        "customer_confirmation_actor_id",
        "customer_confirmation_at",
        "customer_confirmation_fingerprint",
        "supervisor_approval_decision",
        "supervisor_approval_actor_id",
        "supervisor_approval_at",
        "supervisor_approval_fingerprint",
        "idempotency_key",
        "expires_at",
        "execution_attempt_count",
        "execution_lease_owner",
        "execution_lease_expires_at",
        "commerce_resource_id",
        "commerce_status_code",
        "commerce_error_code",
        "verification_status",
        "verified_resource_id",
        "verified_at",
        "version",
        "created_at",
        "updated_at",
    },
    "action_events": {
        "id",
        "action_request_id",
        "tenant_id",
        "sequence",
        "event_type",
        "actor_principal_id",
        "created_at",
        "previous_state",
        "next_state",
        "proposal_fingerprint",
        "correlation_id",
        "reason_code",
    },
}

EXPECTED_CHECKS = {
    "action_request_type_allowed",
    "action_request_state_allowed",
    "action_request_payload_object",
    "action_request_targets_array",
    "action_request_fingerprint_hex",
    "action_request_attempt_non_negative",
    "action_request_version_positive",
    "action_request_expiry_after_creation",
    "action_request_policy_decision_consistent",
    "action_request_confirmation_decision_consistent",
    "action_request_approval_decision_consistent",
    "action_request_verification_status_allowed",
    "action_event_type_allowed",
    "action_event_previous_state_allowed",
    "action_event_next_state_allowed",
    "action_event_fingerprint_hex",
    "action_event_sequence_positive",
}

EXPECTED_INDEXES = {
    "uq_action_requests_originating_tool_invocation",
    "uq_action_requests_idempotency_key",
    "uq_action_requests_active_scope_fingerprint",
    "ix_action_requests_tenant_customer_state_created",
    "uq_action_events_request_sequence",
    "ix_action_events_tenant_action_created",
}


async def _create_action_row(
    postgres_engine: AsyncEngine,
) -> tuple[Stage6ActionContext, ActionRequestRecord]:
    context = await seed_stage6_action_context(postgres_engine, tool_invocation_count=1)
    proposal = CancelOrderProposal(order_id=uuid4())
    action, created = await ActionRepository(
        async_sessionmaker(postgres_engine, expire_on_commit=False)
    ).create_or_get(
        trusted_context=context.trusted_context,
        conversation_id=context.conversation_id,
        agent_run_id=context.agent_run_id,
        tool_invocation_id=context.tool_invocation_ids[0],
        proposal=proposal,
        proposal_fingerprint="a" * 64,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    assert created is True
    return context, action


@pytest.mark.asyncio
async def test_action_tables_have_exact_columns_constraints_and_scoped_indexes(
    postgres_engine: AsyncEngine,
) -> None:
    async with postgres_engine.connect() as connection:
        column_rows = await connection.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name IN "
                "('action_requests', 'action_events')"
            )
        )
        constraint_rows = await connection.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE connamespace = 'public'::regnamespace AND contype = 'c'"
            )
        )
        index_rows = await connection.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname = 'public' AND tablename IN "
                "('action_requests', 'action_events')"
            )
        )
        trigger_rows = await connection.execute(
            text(
                "SELECT t.tgname FROM pg_trigger AS t "
                "JOIN pg_class AS c ON c.oid = t.tgrelid "
                "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relname = 'action_events' "
                "AND NOT t.tgisinternal"
            )
        )

    actual_columns: dict[str, set[str]] = {table: set() for table in EXPECTED_COLUMNS}
    for table, column in column_rows:
        actual_columns[table].add(column)
    assert actual_columns == EXPECTED_COLUMNS

    check_names = set(constraint_rows.scalars())
    assert check_names >= EXPECTED_CHECKS

    indexes: dict[str, str] = {}
    for index_name, definition in index_rows:
        indexes[str(index_name)] = str(definition)
    assert indexes.keys() >= EXPECTED_INDEXES
    active_index = indexes["uq_action_requests_active_scope_fingerprint"]
    assert "WHERE" in active_index
    assert "unresolved" in active_index
    assert "succeeded" not in active_index
    assert set(trigger_rows.scalars()) >= {"trg_action_events_append_only"}


@pytest.mark.asyncio
async def test_confirmation_decision_with_null_fingerprint_is_rejected(
    postgres_engine: AsyncEngine,
) -> None:
    context, action = await _create_action_row(postgres_engine)

    async with postgres_engine.connect() as connection, connection.begin():
        with pytest.raises(DBAPIError):
            async with connection.begin_nested():
                await connection.execute(
                    text(
                        "UPDATE action_requests SET confirmation_required = TRUE, "
                        "customer_confirmation_decision = 'confirmed', "
                        "customer_confirmation_actor_id = :actor_id, "
                        "customer_confirmation_at = :decided_at, "
                        "customer_confirmation_fingerprint = NULL WHERE id = :action_id"
                    ),
                    {
                        "actor_id": context.trusted_context.principal_id,
                        "decided_at": datetime.now(UTC),
                        "action_id": action.id,
                    },
                )


@pytest.mark.asyncio
async def test_fully_bound_confirmation_decision_is_accepted(
    postgres_engine: AsyncEngine,
) -> None:
    context, action = await _create_action_row(postgres_engine)
    decided_at = datetime.now(UTC)

    async with postgres_engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE action_requests SET confirmation_required = TRUE, "
                "customer_confirmation_decision = 'confirmed', "
                "customer_confirmation_actor_id = :actor_id, "
                "customer_confirmation_at = :decided_at, "
                "customer_confirmation_fingerprint = :fingerprint WHERE id = :action_id"
            ),
            {
                "actor_id": context.trusted_context.principal_id,
                "decided_at": decided_at,
                "fingerprint": action.proposal_fingerprint,
                "action_id": action.id,
            },
        )
        decision = (
            await connection.execute(
                text(
                    "SELECT customer_confirmation_decision, customer_confirmation_actor_id, "
                    "customer_confirmation_at, customer_confirmation_fingerprint "
                    "FROM action_requests WHERE id = :action_id"
                ),
                {"action_id": action.id},
            )
        ).one()

    assert decision.customer_confirmation_decision == "confirmed"
    assert decision.customer_confirmation_actor_id == context.trusted_context.principal_id
    assert decision.customer_confirmation_at == decided_at
    assert decision.customer_confirmation_fingerprint == action.proposal_fingerprint


@pytest.mark.asyncio
async def test_confirmation_decision_with_different_valid_fingerprint_is_rejected(
    postgres_engine: AsyncEngine,
) -> None:
    context, action = await _create_action_row(postgres_engine)

    async with postgres_engine.connect() as connection, connection.begin():
        with pytest.raises(DBAPIError):
            async with connection.begin_nested():
                await connection.execute(
                    text(
                        "UPDATE action_requests SET confirmation_required = TRUE, "
                        "customer_confirmation_decision = 'confirmed', "
                        "customer_confirmation_actor_id = :actor_id, "
                        "customer_confirmation_at = :decided_at, "
                        "customer_confirmation_fingerprint = :fingerprint WHERE id = :action_id"
                    ),
                    {
                        "actor_id": context.trusted_context.principal_id,
                        "decided_at": datetime.now(UTC),
                        "fingerprint": "b" * 64,
                        "action_id": action.id,
                    },
                )


@pytest.mark.asyncio
async def test_approval_decision_with_null_fingerprint_is_rejected(
    postgres_engine: AsyncEngine,
) -> None:
    context, action = await _create_action_row(postgres_engine)

    async with postgres_engine.connect() as connection, connection.begin():
        with pytest.raises(DBAPIError):
            async with connection.begin_nested():
                await connection.execute(
                    text(
                        "UPDATE action_requests SET approval_required = TRUE, "
                        "supervisor_approval_decision = 'approved', "
                        "supervisor_approval_actor_id = :actor_id, "
                        "supervisor_approval_at = :decided_at, "
                        "supervisor_approval_fingerprint = NULL WHERE id = :action_id"
                    ),
                    {
                        "actor_id": context.trusted_context.principal_id,
                        "decided_at": datetime.now(UTC),
                        "action_id": action.id,
                    },
                )


@pytest.mark.asyncio
async def test_fully_bound_approval_decision_is_accepted(
    postgres_engine: AsyncEngine,
) -> None:
    context, action = await _create_action_row(postgres_engine)
    decided_at = datetime.now(UTC)

    async with postgres_engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE action_requests SET approval_required = TRUE, "
                "supervisor_approval_decision = 'approved', "
                "supervisor_approval_actor_id = :actor_id, "
                "supervisor_approval_at = :decided_at, "
                "supervisor_approval_fingerprint = :fingerprint WHERE id = :action_id"
            ),
            {
                "actor_id": context.trusted_context.principal_id,
                "decided_at": decided_at,
                "fingerprint": action.proposal_fingerprint,
                "action_id": action.id,
            },
        )
        decision = (
            await connection.execute(
                text(
                    "SELECT supervisor_approval_decision, supervisor_approval_actor_id, "
                    "supervisor_approval_at, supervisor_approval_fingerprint "
                    "FROM action_requests WHERE id = :action_id"
                ),
                {"action_id": action.id},
            )
        ).one()

    assert decision.supervisor_approval_decision == "approved"
    assert decision.supervisor_approval_actor_id == context.trusted_context.principal_id
    assert decision.supervisor_approval_at == decided_at
    assert decision.supervisor_approval_fingerprint == action.proposal_fingerprint


@pytest.mark.asyncio
async def test_approval_decision_with_different_valid_fingerprint_is_rejected(
    postgres_engine: AsyncEngine,
) -> None:
    context, action = await _create_action_row(postgres_engine)

    async with postgres_engine.connect() as connection, connection.begin():
        with pytest.raises(DBAPIError):
            async with connection.begin_nested():
                await connection.execute(
                    text(
                        "UPDATE action_requests SET approval_required = TRUE, "
                        "supervisor_approval_decision = 'approved', "
                        "supervisor_approval_actor_id = :actor_id, "
                        "supervisor_approval_at = :decided_at, "
                        "supervisor_approval_fingerprint = :fingerprint WHERE id = :action_id"
                    ),
                    {
                        "actor_id": context.trusted_context.principal_id,
                        "decided_at": datetime.now(UTC),
                        "fingerprint": "b" * 64,
                        "action_id": action.id,
                    },
                )


@pytest.mark.asyncio
async def test_action_events_reject_update_and_delete_in_postgresql(
    postgres_engine: AsyncEngine,
) -> None:
    now = datetime.now(UTC)
    tenant_id = uuid4()
    principal_id = uuid4()
    customer_id = uuid4()
    conversation_id = uuid4()
    message_id = uuid4()
    agent_run_id = uuid4()
    action_request_id = uuid4()
    event_id = uuid4()
    idempotency_key = uuid4()

    async with postgres_engine.connect() as connection:
        transaction = await connection.begin()
        try:
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
                    "VALUES (:id, :conversation_id, 1, 'user', 'test message', :created_at)"
                ),
                {"id": message_id, "conversation_id": conversation_id, "created_at": now},
            )
            await connection.execute(
                text(
                    "INSERT INTO agent_runs "
                    "(id, conversation_id, user_message_id, status, graph_version, prompt_version, "
                    "tool_schema_version, started_at) "
                    "VALUES (:id, :conversation_id, :message_id, 'running', 'g1', 'p1', 't1', :started_at)"
                ),
                {
                    "id": agent_run_id,
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                    "started_at": now,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO action_requests "
                    "(id, tenant_id, customer_id, proposing_principal_id, conversation_id, agent_run_id, "
                    "action_type, proposal_payload, target_ids, proposal_schema_version, proposal_fingerprint, "
                    "idempotency_key, expires_at) VALUES "
                    "(:id, :tenant_id, :customer_id, :principal_id, :conversation_id, :agent_run_id, "
                    "'cancel_order', CAST(:payload AS jsonb), CAST(:targets AS jsonb), 'action-proposal-v1', "
                    ":fingerprint, :idempotency_key, :expires_at)"
                ),
                {
                    "id": action_request_id,
                    "tenant_id": tenant_id,
                    "customer_id": customer_id,
                    "principal_id": principal_id,
                    "conversation_id": conversation_id,
                    "agent_run_id": agent_run_id,
                    "payload": '{"order_id":"30000000-0000-4000-8000-000000000003"}',
                    "targets": '["30000000-0000-4000-8000-000000000003"]',
                    "fingerprint": "a" * 64,
                    "idempotency_key": idempotency_key,
                    "expires_at": now + timedelta(hours=24),
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO action_events "
                    "(id, action_request_id, tenant_id, sequence, event_type, proposal_fingerprint) "
                    "VALUES (:id, :action_request_id, :tenant_id, 1, 'created', :fingerprint)"
                ),
                {
                    "id": event_id,
                    "action_request_id": action_request_id,
                    "tenant_id": tenant_id,
                    "fingerprint": "a" * 64,
                },
            )

            with pytest.raises(DBAPIError):
                async with connection.begin_nested():
                    await connection.execute(
                        text("UPDATE action_events SET reason_code = 'tampered' WHERE id = :id"),
                        {"id": event_id},
                    )

            with pytest.raises(DBAPIError):
                async with connection.begin_nested():
                    await connection.execute(
                        text("DELETE FROM action_events WHERE id = :id"), {"id": event_id}
                    )
        finally:
            await transaction.rollback()
