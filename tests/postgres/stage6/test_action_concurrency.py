import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from tests.postgres.stage6.conftest import seed_stage6_action_context

from verbaops.actions.models import ActionState, CancelOrderProposal
from verbaops.actions.persistence import ActionEvent, ActionRequest
from verbaops.actions.repository import ActionRepository
from verbaops.actions.transitions import (
    ActionEventType,
    ActionExpiredError,
    ActionTransitionService,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.concurrency,
]


@pytest.mark.asyncio
async def test_concurrent_equivalent_creation_resolves_to_one_active_action(
    postgres_engine: AsyncEngine,
) -> None:
    context = await seed_stage6_action_context(postgres_engine)
    factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    repository = ActionRepository(factory)
    order_id = uuid4()

    results = await asyncio.gather(
        *(
            repository.create_or_get(
                trusted_context=context.trusted_context,
                conversation_id=context.conversation_id,
                agent_run_id=context.agent_run_id,
                tool_invocation_id=invocation_id,
                proposal=CancelOrderProposal(order_id=order_id),
                proposal_fingerprint="9" * 64,
                expires_at=datetime.now(UTC) + timedelta(hours=24),
            )
            for invocation_id in context.tool_invocation_ids
        )
    )

    assert len({record.id for record, _ in results}) == 1
    assert sorted(created for _, created in results) == [False, True]
    action_id = results[0][0].id
    async with postgres_engine.connect() as connection:
        request_count = await connection.scalar(
            select(func.count()).select_from(ActionRequest).where(ActionRequest.id == action_id)
        )
        event_count = await connection.scalar(
            select(func.count())
            .select_from(ActionEvent)
            .where(ActionEvent.action_request_id == action_id)
        )
    assert request_count == 1
    assert event_count == 1


@pytest.mark.asyncio
@pytest.mark.critical_race
async def test_expiry_race_serializes_and_records_one_expiration(
    postgres_engine: AsyncEngine,
) -> None:
    context = await seed_stage6_action_context(postgres_engine)
    factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    repository = ActionRepository(factory)
    service = ActionTransitionService(factory)
    action, _ = await repository.create_or_get(
        trusted_context=context.trusted_context,
        conversation_id=context.conversation_id,
        agent_run_id=context.agent_run_id,
        tool_invocation_id=context.tool_invocation_ids[0],
        proposal=CancelOrderProposal(order_id=uuid4()),
        proposal_fingerprint="8" * 64,
        expires_at=datetime.now(UTC) + timedelta(milliseconds=150),
    )
    await asyncio.sleep(0.2)

    outcomes = await asyncio.gather(
        *(
            service.transition(
                action.id,
                context.trusted_context.tenant_id,
                action.proposal_fingerprint,
                ActionState.READY_TO_EXECUTE,
                context.trusted_context.principal_id,
                ActionEventType.STATE_TRANSITION,
                "ready",
            )
            for _ in range(2)
        ),
        return_exceptions=True,
    )

    assert all(isinstance(outcome, ActionExpiredError) for outcome in outcomes)
    async with postgres_engine.connect() as connection:
        stored_state = await connection.scalar(
            select(ActionRequest.state).where(ActionRequest.id == action.id)
        )
        event_types = (
            (
                await connection.execute(
                    select(ActionEvent.event_type)
                    .where(ActionEvent.action_request_id == action.id)
                    .order_by(ActionEvent.sequence)
                )
            )
            .scalars()
            .all()
        )
    assert stored_state == ActionState.EXPIRED.value
    assert event_types == ["created", "expired"]
