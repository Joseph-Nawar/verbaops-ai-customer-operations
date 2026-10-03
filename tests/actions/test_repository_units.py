from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.actions._fake_sessions import (
    FakeActionSession,
    FakeSessionFactory,
    action_context,
    action_request,
)
from verbaops.actions.models import ActionState, CancelOrderProposal
from verbaops.actions.persistence import ActionEvent, ActionRequest
from verbaops.actions.repository import (
    ActionInFlightError,
    ActionOriginConflictError,
    ActionRepository,
    ActionScopeError,
    ProposalFingerprintCollisionError,
)


def _repository(factory: FakeSessionFactory) -> ActionRepository:
    return ActionRepository(cast(async_sessionmaker[AsyncSession], factory))


@pytest.mark.asyncio
async def test_create_uses_trusted_scope_and_adds_request_with_created_event() -> None:
    context = action_context()
    conversation_id = uuid4()
    agent_run_id = uuid4()
    invocation_id = uuid4()
    session = FakeActionSession(
        scalar_values=[object(), agent_run_id, invocation_id, None, None],
        scalar_rows=[[]],
    )
    repository = _repository(FakeSessionFactory(session))
    proposal = CancelOrderProposal(order_id=uuid4())

    record, created = await repository.create_or_get(
        trusted_context=context,
        conversation_id=conversation_id,
        agent_run_id=agent_run_id,
        tool_invocation_id=invocation_id,
        proposal=proposal,
        proposal_fingerprint="a" * 64,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )

    assert created is True
    assert record.state is ActionState.PROPOSED
    assert record.tenant_id == context.tenant_id
    assert record.customer_id == context.customer_id
    assert record.proposing_principal_id == context.principal_id
    assert record.conversation_id == conversation_id
    assert record.agent_run_id == agent_run_id
    assert record.originating_tool_invocation_id == invocation_id
    assert record.idempotency_key.int != 0
    request = next(event for event in session.added if isinstance(event, ActionRequest))
    event = next(event for event in session.added if isinstance(event, ActionEvent))
    assert request.id == record.id
    assert event.sequence == 1
    assert event.event_type == "created"
    assert event.proposal_fingerprint == "a" * 64


@pytest.mark.asyncio
async def test_origin_replay_returns_existing_action_without_second_insert() -> None:
    context = action_context()
    conversation_id = uuid4()
    agent_run_id = uuid4()
    invocation_id = uuid4()
    existing = action_request(
        trusted_context=context,
        conversation_id=conversation_id,
        agent_run_id=agent_run_id,
        tool_invocation_id=invocation_id,
        proposal_fingerprint="b" * 64,
    )
    session = FakeActionSession(scalar_values=[object(), agent_run_id, invocation_id, existing])

    record, created = await _repository(FakeSessionFactory(session)).create_or_get(
        trusted_context=context,
        conversation_id=conversation_id,
        agent_run_id=agent_run_id,
        tool_invocation_id=invocation_id,
        proposal=CancelOrderProposal(order_id=uuid4()),
        proposal_fingerprint="c" * 64,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )

    assert created is False
    assert record.id == existing.id
    assert session.added == []


@pytest.mark.asyncio
async def test_active_fingerprint_replay_requires_same_payload_and_target() -> None:
    context = action_context()
    conversation_id = uuid4()
    agent_run_id = uuid4()
    invocation_id = uuid4()
    proposal = CancelOrderProposal(order_id=uuid4())
    existing = action_request(
        trusted_context=context,
        conversation_id=conversation_id,
        agent_run_id=agent_run_id,
        order_id=proposal.order_id,
        proposal_fingerprint="d" * 64,
    )
    session = FakeActionSession(
        scalar_values=[object(), agent_run_id, invocation_id, None, existing]
    )

    record, created = await _repository(FakeSessionFactory(session)).create_or_get(
        trusted_context=context,
        conversation_id=conversation_id,
        agent_run_id=agent_run_id,
        tool_invocation_id=invocation_id,
        proposal=proposal,
        proposal_fingerprint="d" * 64,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )

    assert created is False
    assert record.id == existing.id
    assert session.added == []


@pytest.mark.asyncio
async def test_changed_material_expires_prior_undispatched_row_in_same_transaction() -> None:
    context = action_context()
    conversation_id = uuid4()
    agent_run_id = uuid4()
    invocation_id = uuid4()
    order_id = uuid4()
    prior = action_request(
        trusted_context=context,
        conversation_id=conversation_id,
        agent_run_id=agent_run_id,
        order_id=order_id,
        proposal_fingerprint="e" * 64,
    )
    session = FakeActionSession(
        scalar_values=[object(), agent_run_id, invocation_id, None, None],
        scalar_rows=[[prior]],
        record=prior,
    )

    record, created = await _repository(FakeSessionFactory(session)).create_or_get(
        trusted_context=context,
        conversation_id=conversation_id,
        agent_run_id=agent_run_id,
        tool_invocation_id=invocation_id,
        proposal=CancelOrderProposal(order_id=order_id),
        proposal_fingerprint="f" * 64,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )

    assert created is True
    assert record.state is ActionState.PROPOSED
    assert prior.state == ActionState.EXPIRED.value
    assert [event.event_type for event in session.added if isinstance(event, ActionEvent)] == [
        "expired",
        "created",
    ]


@pytest.mark.asyncio
async def test_changed_material_leaves_dispatched_row_for_reconciliation() -> None:
    context = action_context()
    conversation_id = uuid4()
    agent_run_id = uuid4()
    invocation_id = uuid4()
    order_id = uuid4()
    prior = action_request(
        trusted_context=context,
        conversation_id=conversation_id,
        agent_run_id=agent_run_id,
        order_id=order_id,
        proposal_fingerprint="1" * 64,
        state=ActionState.UNRESOLVED,
    )
    session = FakeActionSession(
        scalar_values=[object(), agent_run_id, invocation_id, None, None],
        scalar_rows=[[prior]],
    )

    with pytest.raises(ActionInFlightError):
        await _repository(FakeSessionFactory(session)).create_or_get(
            trusted_context=context,
            conversation_id=conversation_id,
            agent_run_id=agent_run_id,
            tool_invocation_id=invocation_id,
            proposal=CancelOrderProposal(order_id=order_id),
            proposal_fingerprint="2" * 64,
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
    assert prior.state == ActionState.UNRESOLVED.value
    assert session.added == []


@pytest.mark.asyncio
async def test_scope_and_fingerprint_conflicts_fail_closed() -> None:
    context = action_context()
    proposal = CancelOrderProposal(order_id=uuid4())
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        await _repository(FakeSessionFactory()).create_or_get(
            trusted_context=context,
            conversation_id=uuid4(),
            agent_run_id=uuid4(),
            tool_invocation_id=uuid4(),
            proposal=proposal,
            proposal_fingerprint="not-a-fingerprint",
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )

    session = FakeActionSession(scalar_values=[None])
    with pytest.raises(ActionScopeError, match="conversation"):
        await _repository(FakeSessionFactory(session)).create_or_get(
            trusted_context=context,
            conversation_id=uuid4(),
            agent_run_id=uuid4(),
            tool_invocation_id=uuid4(),
            proposal=proposal,
            proposal_fingerprint="3" * 64,
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )

    wrong_scope_request = action_request(
        trusted_context=action_context(),
        conversation_id=uuid4(),
        agent_run_id=uuid4(),
        tool_invocation_id=uuid4(),
    )
    wrong_scope_invocation_id = wrong_scope_request.originating_tool_invocation_id
    assert wrong_scope_invocation_id is not None
    scoped_session = FakeActionSession(
        scalar_values=[object(), uuid4(), uuid4(), wrong_scope_request]
    )
    with pytest.raises(ActionOriginConflictError):
        await _repository(FakeSessionFactory(scoped_session)).create_or_get(
            trusted_context=context,
            conversation_id=uuid4(),
            agent_run_id=uuid4(),
            tool_invocation_id=wrong_scope_invocation_id,
            proposal=proposal,
            proposal_fingerprint="4" * 64,
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )


@pytest.mark.asyncio
async def test_unique_conflict_loads_scoped_winner_after_rollback() -> None:
    context = action_context()
    conversation_id = uuid4()
    agent_run_id = uuid4()
    invocation_id = uuid4()
    proposal = CancelOrderProposal(order_id=uuid4())
    fingerprint = "5" * 64
    winner = action_request(
        trusted_context=context,
        conversation_id=conversation_id,
        agent_run_id=agent_run_id,
        proposal_fingerprint=fingerprint,
        order_id=proposal.order_id,
    )
    insert_session = FakeActionSession(
        scalar_values=[object(), agent_run_id, invocation_id, None, None],
        scalar_rows=[[]],
        fail_flush_at=1,
    )
    winner_session = FakeActionSession(scalar_values=[None, winner])
    repository = _repository(FakeSessionFactory(insert_session, winner_session))

    record, created = await repository.create_or_get(
        trusted_context=context,
        conversation_id=conversation_id,
        agent_run_id=agent_run_id,
        tool_invocation_id=invocation_id,
        proposal=proposal,
        proposal_fingerprint=fingerprint,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )

    assert created is False
    assert record.id == winner.id


def test_same_fingerprint_cannot_hide_changed_payload_material() -> None:
    from verbaops.actions.repository import _same_proposal

    row = action_request(proposal_fingerprint="6" * 64)
    with pytest.raises(ProposalFingerprintCollisionError):
        _same_proposal(
            row,
            action_type="cancel_order",
            payload={"action_type": "cancel_order", "order_id": str(uuid4())},
            target_ids=[str(uuid4())],
            fingerprint="6" * 64,
        )
