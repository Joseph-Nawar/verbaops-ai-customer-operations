import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from tests.postgres.stage6.conftest import Stage6ActionContext, seed_stage6_action_context

from verbaops.actions.models import ActionState, CancelOrderProposal
from verbaops.actions.persistence import ActionEvent, ActionRequest
from verbaops.actions.policy import PolicyDecision
from verbaops.actions.repository import ActionInFlightError, ActionRepository, ActionRequestRecord
from verbaops.actions.transitions import (
    ActionEventType,
    ActionExpiredError,
    ActionRequestNotFoundError,
    ActionTransitionService,
    InvalidActionTransitionError,
    ProposalFingerprintMismatchError,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.contract]


def _repository(postgres_engine: AsyncEngine) -> ActionRepository:
    return ActionRepository(async_sessionmaker(postgres_engine, expire_on_commit=False))


def _service(postgres_engine: AsyncEngine) -> ActionTransitionService:
    return ActionTransitionService(async_sessionmaker(postgres_engine, expire_on_commit=False))


async def _create(
    repository: ActionRepository,
    context: Stage6ActionContext,
    *,
    invocation_index: int = 0,
    order_id: UUID | None = None,
    fingerprint: str = "a" * 64,
    expires_at: datetime | None = None,
) -> tuple[ActionRequestRecord, bool]:
    return await repository.create_or_get(
        trusted_context=context.trusted_context,
        conversation_id=context.conversation_id,
        agent_run_id=context.agent_run_id,
        tool_invocation_id=context.tool_invocation_ids[invocation_index],
        proposal=CancelOrderProposal(order_id=order_id or uuid4()),
        proposal_fingerprint=fingerprint,
        expires_at=expires_at or datetime.now(UTC) + timedelta(hours=24),
    )


@pytest.mark.asyncio
async def test_create_is_atomic_and_replay_returns_one_request_and_created_event(
    postgres_engine: AsyncEngine,
) -> None:
    context = await seed_stage6_action_context(postgres_engine)
    repository = _repository(postgres_engine)
    order_id = uuid4()

    first, created = await repository.create_or_get(
        trusted_context=context.trusted_context,
        conversation_id=context.conversation_id,
        agent_run_id=context.agent_run_id,
        tool_invocation_id=context.tool_invocation_ids[0],
        proposal=CancelOrderProposal(order_id=order_id),
        proposal_fingerprint="b" * 64,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    replay, replay_created = await repository.create_or_get(
        trusted_context=context.trusted_context,
        conversation_id=context.conversation_id,
        agent_run_id=context.agent_run_id,
        tool_invocation_id=context.tool_invocation_ids[0],
        proposal=CancelOrderProposal(order_id=order_id),
        proposal_fingerprint="b" * 64,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )

    assert created is True
    assert replay_created is False
    assert first.id == replay.id
    assert first.state is ActionState.PROPOSED
    assert first.idempotency_key != UUID(int=0)
    async with postgres_engine.connect() as connection:
        assert (
            await connection.scalar(
                select(func.count()).select_from(ActionRequest).where(ActionRequest.id == first.id)
            )
            == 1
        )
        events = (
            await connection.execute(
                select(ActionEvent.sequence, ActionEvent.event_type).where(
                    ActionEvent.action_request_id == first.id
                )
            )
        ).all()
    assert [(event.sequence, event.event_type) for event in events] == [(1, "created")]


@pytest.mark.asyncio
async def test_create_event_failure_rolls_back_the_new_action_request(
    postgres_engine: AsyncEngine,
) -> None:
    context = await seed_stage6_action_context(postgres_engine)
    suffix = uuid4().hex
    function_name = f"test_fail_action_creation_{suffix}"
    trigger_name = f"test_fail_action_creation_trigger_{suffix}"
    async with postgres_engine.begin() as connection:
        await connection.execute(
            text(
                f"CREATE FUNCTION {function_name}() RETURNS trigger LANGUAGE plpgsql AS "
                "$$ BEGIN IF NEW.event_type = 'created' THEN "
                "RAISE EXCEPTION 'forced creation event failure'; END IF; RETURN NEW; END; $$"
            )
        )
        await connection.execute(
            text(
                f"CREATE TRIGGER {trigger_name} BEFORE INSERT ON action_events "
                f"FOR EACH ROW EXECUTE FUNCTION {function_name}()"
            )
        )
    try:
        with pytest.raises(DBAPIError, match="forced creation event failure"):
            await _create(_repository(postgres_engine), context)
    finally:
        async with postgres_engine.begin() as connection:
            await connection.execute(text(f"DROP TRIGGER {trigger_name} ON action_events"))
            await connection.execute(text(f"DROP FUNCTION {function_name}()"))

    async with postgres_engine.connect() as connection:
        request_count = await connection.scalar(
            select(func.count())
            .select_from(ActionRequest)
            .where(ActionRequest.conversation_id == context.conversation_id)
        )
        event_count = await connection.scalar(
            select(func.count())
            .select_from(ActionEvent)
            .where(ActionEvent.tenant_id == context.trusted_context.tenant_id)
        )
    assert request_count == 0
    assert event_count == 0


@pytest.mark.asyncio
async def test_identical_active_proposal_deduplicates_across_tool_invocations(
    postgres_engine: AsyncEngine,
) -> None:
    context = await seed_stage6_action_context(postgres_engine)
    repository = _repository(postgres_engine)
    order_id = uuid4()

    first, first_created = await _create(
        repository, context, invocation_index=0, order_id=order_id, fingerprint="c" * 64
    )
    duplicate, duplicate_created = await _create(
        repository, context, invocation_index=1, order_id=order_id, fingerprint="c" * 64
    )

    assert first_created is True
    assert duplicate_created is False
    assert duplicate.id == first.id


@pytest.mark.asyncio
async def test_durable_tool_invocation_cannot_create_a_second_changed_action(
    postgres_engine: AsyncEngine,
) -> None:
    context = await seed_stage6_action_context(postgres_engine)
    repository = _repository(postgres_engine)
    original, created = await _create(
        repository,
        context,
        invocation_index=0,
        order_id=uuid4(),
        fingerprint="3" * 64,
    )
    replay, replay_created = await _create(
        repository,
        context,
        invocation_index=0,
        order_id=uuid4(),
        fingerprint="4" * 64,
    )

    assert created is True
    assert replay_created is False
    assert replay.id == original.id


@pytest.mark.asyncio
async def test_changed_material_expires_only_matching_undispatched_request(
    postgres_engine: AsyncEngine,
) -> None:
    context = await seed_stage6_action_context(postgres_engine)
    repository = _repository(postgres_engine)
    order_id = uuid4()

    old, _ = await _create(
        repository, context, invocation_index=0, order_id=order_id, fingerprint="d" * 64
    )
    policy = PolicyDecision(
        allowed=True,
        reason_code="allowed",
        confirmation_required=True,
        approval_required=False,
        policy_version="stage6-policy-v1",
    )
    await _service(postgres_engine).transition(
        old.id,
        context.trusted_context.tenant_id,
        old.proposal_fingerprint,
        ActionState.AWAITING_CONFIRMATION,
        context.trusted_context.principal_id,
        ActionEventType.POLICY_ALLOWED,
        "allowed",
        policy_decision=policy,
    )
    changed, created = await _create(
        repository, context, invocation_index=1, order_id=order_id, fingerprint="e" * 64
    )

    assert created is True
    assert changed.id != old.id
    async with postgres_engine.connect() as connection:
        old_request = await connection.scalar(
            select(ActionRequest.state).where(ActionRequest.id == old.id)
        )
        old_events = (
            await connection.execute(
                select(ActionEvent.event_type, ActionEvent.reason_code).where(
                    ActionEvent.action_request_id == old.id
                )
            )
        ).all()
    assert old_request == ActionState.EXPIRED.value
    assert [(event.event_type, event.reason_code) for event in old_events] == [
        ("created", None),
        ("policy_allowed", "allowed"),
        ("expired", "superseded"),
    ]
    assert changed.policy_allowed is None
    assert changed.confirmation_required is False
    assert changed.approval_required is False


@pytest.mark.asyncio
async def test_different_targets_remain_independent(
    postgres_engine: AsyncEngine,
) -> None:
    context = await seed_stage6_action_context(postgres_engine)
    repository = _repository(postgres_engine)

    first, _ = await _create(
        repository,
        context,
        invocation_index=0,
        order_id=uuid4(),
        fingerprint="f" * 64,
    )
    second, created = await _create(
        repository,
        context,
        invocation_index=1,
        order_id=uuid4(),
        fingerprint="1" * 64,
    )

    assert created is True
    assert second.id != first.id
    async with postgres_engine.connect() as connection:
        states = (
            (
                await connection.execute(
                    select(ActionRequest.state).where(ActionRequest.id.in_([first.id, second.id]))
                )
            )
            .scalars()
            .all()
        )
    assert states == [ActionState.PROPOSED.value, ActionState.PROPOSED.value]


@pytest.mark.asyncio
async def test_changed_proposal_does_not_supersede_dispatched_work(
    postgres_engine: AsyncEngine,
) -> None:
    context = await seed_stage6_action_context(postgres_engine)
    repository = _repository(postgres_engine)
    service = _service(postgres_engine)
    order_id = uuid4()
    old, _ = await _create(
        repository, context, invocation_index=0, order_id=order_id, fingerprint="5" * 64
    )
    policy = PolicyDecision(
        allowed=True,
        reason_code="allowed",
        confirmation_required=True,
        approval_required=False,
        policy_version="stage6-policy-v1",
    )
    await service.transition(
        old.id,
        context.trusted_context.tenant_id,
        old.proposal_fingerprint,
        ActionState.AWAITING_CONFIRMATION,
        context.trusted_context.principal_id,
        ActionEventType.POLICY_ALLOWED,
        "allowed",
        policy_decision=policy,
    )
    await service.transition(
        old.id,
        context.trusted_context.tenant_id,
        old.proposal_fingerprint,
        ActionState.READY_TO_EXECUTE,
        context.trusted_context.principal_id,
        ActionEventType.CUSTOMER_CONFIRMED,
        "confirmed",
    )
    await service.transition(
        old.id,
        context.trusted_context.tenant_id,
        old.proposal_fingerprint,
        ActionState.EXECUTING,
        context.trusted_context.principal_id,
        ActionEventType.EXECUTION_STARTED,
        "execution_started",
    )

    with pytest.raises(ActionInFlightError):
        await _create(
            repository,
            context,
            invocation_index=1,
            order_id=order_id,
            fingerprint="6" * 64,
        )
    async with postgres_engine.connect() as connection:
        current_state = await connection.scalar(
            select(ActionRequest.state).where(ActionRequest.id == old.id)
        )
    assert current_state == ActionState.EXECUTING.value


@pytest.mark.asyncio
async def test_terminal_request_allows_a_fresh_later_intent(
    postgres_engine: AsyncEngine,
) -> None:
    context = await seed_stage6_action_context(postgres_engine)
    repository = _repository(postgres_engine)
    old, _ = await _create(
        repository,
        context,
        invocation_index=0,
        order_id=uuid4(),
        fingerprint="2" * 64,
    )
    denial = PolicyDecision(
        allowed=False,
        reason_code="proposal_denied",
        confirmation_required=False,
        approval_required=False,
        policy_version="stage6-policy-v1",
    )

    denied = await _service(postgres_engine).transition(
        old.id,
        context.trusted_context.tenant_id,
        old.proposal_fingerprint,
        ActionState.POLICY_DENIED,
        context.trusted_context.principal_id,
        ActionEventType.POLICY_DENIED,
        "policy_denied",
        policy_decision=denial,
    )
    later, created = await _create(
        repository,
        context,
        invocation_index=1,
        order_id=old.target_ids[0],
        fingerprint=old.proposal_fingerprint,
    )

    assert denied.state is ActionState.POLICY_DENIED
    assert created is True
    assert later.id != old.id
    assert later.idempotency_key != old.idempotency_key


@pytest.mark.asyncio
async def test_transition_persists_policy_gates_and_one_bounded_event_atomically(
    postgres_engine: AsyncEngine,
) -> None:
    context = await seed_stage6_action_context(postgres_engine)
    action, _ = await _create(_repository(postgres_engine), context)
    decision = PolicyDecision(
        allowed=True,
        reason_code="allowed",
        confirmation_required=True,
        approval_required=False,
        policy_version="stage6-policy-v1",
    )

    transitioned = await _service(postgres_engine).transition(
        action.id,
        context.trusted_context.tenant_id,
        action.proposal_fingerprint,
        ActionState.AWAITING_CONFIRMATION,
        context.trusted_context.principal_id,
        ActionEventType.POLICY_ALLOWED,
        "allowed",
        policy_decision=decision,
    )

    assert transitioned.state is ActionState.AWAITING_CONFIRMATION
    assert transitioned.version == 2
    assert transitioned.policy_allowed is True
    assert transitioned.confirmation_required is True
    assert transitioned.approval_required is False
    async with postgres_engine.connect() as connection:
        events = (
            await connection.execute(
                select(ActionEvent.event_type, ActionEvent.sequence, ActionEvent.reason_code)
                .where(ActionEvent.action_request_id == action.id)
                .order_by(ActionEvent.sequence)
            )
        ).all()
    assert [event.event_type for event in events] == ["created", "policy_allowed"]
    assert [event.sequence for event in events] == [1, 2]
    assert all(event.reason_code in {None, "allowed"} for event in events)


@pytest.mark.asyncio
async def test_transition_event_failure_rolls_back_state_and_version(
    postgres_engine: AsyncEngine,
) -> None:
    context = await seed_stage6_action_context(postgres_engine)
    action, _ = await _create(_repository(postgres_engine), context)
    suffix = uuid4().hex
    function_name = f"test_fail_action_event_{suffix}"
    trigger_name = f"test_fail_action_event_trigger_{suffix}"
    async with postgres_engine.begin() as connection:
        await connection.execute(
            text(
                f"CREATE FUNCTION {function_name}() RETURNS trigger LANGUAGE plpgsql AS "
                "$$ BEGIN IF NEW.event_type = 'policy_allowed' THEN "
                "RAISE EXCEPTION 'forced event failure'; END IF; RETURN NEW; END; $$"
            )
        )
        await connection.execute(
            text(
                f"CREATE TRIGGER {trigger_name} BEFORE INSERT ON action_events "
                f"FOR EACH ROW EXECUTE FUNCTION {function_name}()"
            )
        )
    try:
        failing_decision = PolicyDecision(
            allowed=True,
            reason_code="allowed",
            confirmation_required=True,
            approval_required=False,
            policy_version="stage6-policy-v1",
        )
        with pytest.raises(DBAPIError, match="forced event failure"):
            await _service(postgres_engine).transition(
                action.id,
                context.trusted_context.tenant_id,
                action.proposal_fingerprint,
                ActionState.AWAITING_CONFIRMATION,
                context.trusted_context.principal_id,
                ActionEventType.POLICY_ALLOWED,
                "allowed",
                policy_decision=failing_decision,
            )
    finally:
        async with postgres_engine.begin() as connection:
            await connection.execute(text(f"DROP TRIGGER {trigger_name} ON action_events"))
            await connection.execute(text(f"DROP FUNCTION {function_name}()"))

    async with postgres_engine.connect() as connection:
        stored = await connection.execute(
            select(ActionRequest.state, ActionRequest.version).where(ActionRequest.id == action.id)
        )
        stored_state, stored_version = stored.one()
        event_count = await connection.scalar(
            select(func.count())
            .select_from(ActionEvent)
            .where(ActionEvent.action_request_id == action.id)
        )
    assert stored_state == ActionState.PROPOSED.value
    assert stored_version == 1
    assert event_count == 1


@pytest.mark.asyncio
async def test_transition_requires_tenant_and_exact_fingerprint(
    postgres_engine: AsyncEngine,
) -> None:
    context = await seed_stage6_action_context(postgres_engine)
    action, _ = await _create(_repository(postgres_engine), context)
    service = _service(postgres_engine)

    with pytest.raises(ActionRequestNotFoundError):
        await service.transition(
            action.id,
            uuid4(),
            action.proposal_fingerprint,
            ActionState.AWAITING_CONFIRMATION,
            None,
            ActionEventType.STATE_TRANSITION,
            "test",
        )
    with pytest.raises(ProposalFingerprintMismatchError):
        await service.transition(
            action.id,
            context.trusted_context.tenant_id,
            "0" * 64,
            ActionState.AWAITING_CONFIRMATION,
            None,
            ActionEventType.STATE_TRANSITION,
            "test",
        )


@pytest.mark.asyncio
async def test_human_decisions_bind_actor_and_fingerprint_to_the_request(
    postgres_engine: AsyncEngine,
) -> None:
    context = await seed_stage6_action_context(postgres_engine)
    action, _ = await _create(_repository(postgres_engine), context)
    service = _service(postgres_engine)
    decision = PolicyDecision(
        allowed=True,
        reason_code="allowed",
        confirmation_required=True,
        approval_required=True,
        policy_version="stage6-policy-v1",
    )

    awaiting_approval = await service.transition(
        action.id,
        context.trusted_context.tenant_id,
        action.proposal_fingerprint,
        ActionState.AWAITING_APPROVAL,
        context.trusted_context.principal_id,
        ActionEventType.POLICY_ALLOWED,
        "approval_required",
        policy_decision=decision,
    )
    awaiting_confirmation = await service.transition(
        action.id,
        context.trusted_context.tenant_id,
        action.proposal_fingerprint,
        ActionState.AWAITING_CONFIRMATION,
        context.trusted_context.principal_id,
        ActionEventType.SUPERVISOR_APPROVED,
        "approved",
    )
    ready = await service.transition(
        action.id,
        context.trusted_context.tenant_id,
        action.proposal_fingerprint,
        ActionState.READY_TO_EXECUTE,
        context.trusted_context.principal_id,
        ActionEventType.CUSTOMER_CONFIRMED,
        "confirmed",
    )

    assert awaiting_approval.supervisor_approval_decision is None
    assert awaiting_confirmation.supervisor_approval_decision == "approved"
    assert (
        awaiting_confirmation.supervisor_approval_actor_id == context.trusted_context.principal_id
    )
    assert awaiting_confirmation.supervisor_approval_fingerprint == action.proposal_fingerprint
    assert ready.customer_confirmation_decision == "confirmed"
    assert ready.customer_confirmation_actor_id == context.trusted_context.principal_id
    assert ready.customer_confirmation_fingerprint == action.proposal_fingerprint


@pytest.mark.asyncio
async def test_confirmation_gate_cannot_be_skipped_with_generic_transition(
    postgres_engine: AsyncEngine,
) -> None:
    context = await seed_stage6_action_context(postgres_engine)
    action, _ = await _create(_repository(postgres_engine), context)
    service = _service(postgres_engine)
    decision = PolicyDecision(
        allowed=True,
        reason_code="allowed",
        confirmation_required=True,
        approval_required=False,
        policy_version="stage6-policy-v1",
    )
    await service.transition(
        action.id,
        context.trusted_context.tenant_id,
        action.proposal_fingerprint,
        ActionState.AWAITING_CONFIRMATION,
        context.trusted_context.principal_id,
        ActionEventType.POLICY_ALLOWED,
        "allowed",
        policy_decision=decision,
    )

    with pytest.raises(InvalidActionTransitionError):
        await service.transition(
            action.id,
            context.trusted_context.tenant_id,
            action.proposal_fingerprint,
            ActionState.READY_TO_EXECUTE,
            context.trusted_context.principal_id,
            ActionEventType.STATE_TRANSITION,
            "ready",
        )


@pytest.mark.asyncio
async def test_execution_retry_requires_proven_non_dispatch_reason(
    postgres_engine: AsyncEngine,
) -> None:
    context = await seed_stage6_action_context(postgres_engine)
    action, _ = await _create(_repository(postgres_engine), context)
    service = _service(postgres_engine)
    confirmation = PolicyDecision(
        allowed=True,
        reason_code="allowed",
        confirmation_required=True,
        approval_required=False,
        policy_version="stage6-policy-v1",
    )
    await service.transition(
        action.id,
        context.trusted_context.tenant_id,
        action.proposal_fingerprint,
        ActionState.AWAITING_CONFIRMATION,
        context.trusted_context.principal_id,
        ActionEventType.POLICY_ALLOWED,
        "allowed",
        policy_decision=confirmation,
    )
    await service.transition(
        action.id,
        context.trusted_context.tenant_id,
        action.proposal_fingerprint,
        ActionState.READY_TO_EXECUTE,
        context.trusted_context.principal_id,
        ActionEventType.CUSTOMER_CONFIRMED,
        "confirmed",
    )
    await service.transition(
        action.id,
        context.trusted_context.tenant_id,
        action.proposal_fingerprint,
        ActionState.EXECUTING,
        context.trusted_context.principal_id,
        ActionEventType.EXECUTION_STARTED,
        "execution_started",
    )

    with pytest.raises(InvalidActionTransitionError):
        await service.transition(
            action.id,
            context.trusted_context.tenant_id,
            action.proposal_fingerprint,
            ActionState.READY_TO_EXECUTE,
            context.trusted_context.principal_id,
            ActionEventType.STATE_TRANSITION,
            "retry",
        )
    retried = await service.transition(
        action.id,
        context.trusted_context.tenant_id,
        action.proposal_fingerprint,
        ActionState.READY_TO_EXECUTE,
        context.trusted_context.principal_id,
        ActionEventType.STATE_TRANSITION,
        "proven_non_dispatch",
    )

    assert retried.state is ActionState.READY_TO_EXECUTE
    assert retried.version == 5


@pytest.mark.asyncio
async def test_success_requires_verified_read_back_resource_evidence(
    postgres_engine: AsyncEngine,
) -> None:
    context = await seed_stage6_action_context(postgres_engine)
    action, _ = await _create(_repository(postgres_engine), context)
    service = _service(postgres_engine)
    confirmation = PolicyDecision(
        allowed=True,
        reason_code="allowed",
        confirmation_required=True,
        approval_required=False,
        policy_version="stage6-policy-v1",
    )
    await service.transition(
        action.id,
        context.trusted_context.tenant_id,
        action.proposal_fingerprint,
        ActionState.AWAITING_CONFIRMATION,
        context.trusted_context.principal_id,
        ActionEventType.POLICY_ALLOWED,
        "allowed",
        policy_decision=confirmation,
    )
    await service.transition(
        action.id,
        context.trusted_context.tenant_id,
        action.proposal_fingerprint,
        ActionState.READY_TO_EXECUTE,
        context.trusted_context.principal_id,
        ActionEventType.CUSTOMER_CONFIRMED,
        "confirmed",
    )
    await service.transition(
        action.id,
        context.trusted_context.tenant_id,
        action.proposal_fingerprint,
        ActionState.EXECUTING,
        context.trusted_context.principal_id,
        ActionEventType.EXECUTION_STARTED,
        "execution_started",
    )

    with pytest.raises(InvalidActionTransitionError):
        await service.transition(
            action.id,
            context.trusted_context.tenant_id,
            action.proposal_fingerprint,
            ActionState.SUCCEEDED,
            context.trusted_context.principal_id,
            ActionEventType.VERIFICATION_SUCCEEDED,
            "verified",
        )
    result_id = uuid4()
    succeeded = await service.transition(
        action.id,
        context.trusted_context.tenant_id,
        action.proposal_fingerprint,
        ActionState.SUCCEEDED,
        context.trusted_context.principal_id,
        ActionEventType.VERIFICATION_SUCCEEDED,
        "verified",
        verified_resource_id=result_id,
    )

    assert succeeded.state is ActionState.SUCCEEDED
    assert succeeded.verification_status == "verified"
    assert succeeded.verified_resource_id == result_id
    assert succeeded.verified_at is not None


@pytest.mark.asyncio
async def test_expired_undispatched_request_cannot_advance(
    postgres_engine: AsyncEngine,
) -> None:
    context = await seed_stage6_action_context(postgres_engine)
    expires_at = datetime.now(UTC) + timedelta(milliseconds=100)
    action, _ = await _create(_repository(postgres_engine), context, expires_at=expires_at)
    await asyncio.sleep(0.15)

    with pytest.raises(ActionExpiredError):
        await _service(postgres_engine).transition(
            action.id,
            context.trusted_context.tenant_id,
            action.proposal_fingerprint,
            ActionState.AWAITING_CONFIRMATION,
            context.trusted_context.principal_id,
            ActionEventType.STATE_TRANSITION,
            "confirmation_required",
        )
    async with postgres_engine.connect() as connection:
        stored_state = await connection.scalar(
            select(ActionRequest.state).where(ActionRequest.id == action.id)
        )
        events = (
            await connection.execute(
                select(ActionEvent.event_type, ActionEvent.reason_code).where(
                    ActionEvent.action_request_id == action.id
                )
            )
        ).all()
    assert stored_state == ActionState.EXPIRED.value
    assert [(event.event_type, event.reason_code) for event in events[-1:]] == [
        ("expired", "expired")
    ]
