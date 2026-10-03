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
from verbaops.actions.models import ActionState
from verbaops.actions.persistence import ActionEvent
from verbaops.actions.policy import PolicyDecision
from verbaops.actions.transitions import (
    ActionEventType,
    ActionExpiredError,
    ActionPolicyDecisionRequiredError,
    ActionRequestNotFoundError,
    ActionTransitionService,
    InvalidActionTransitionError,
    ProposalFingerprintMismatchError,
    validate_action_transition,
)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ActionState.PROPOSED, ActionState.POLICY_DENIED),
        (ActionState.PROPOSED, ActionState.AWAITING_APPROVAL),
        (ActionState.PROPOSED, ActionState.AWAITING_CONFIRMATION),
        (ActionState.PROPOSED, ActionState.READY_TO_EXECUTE),
        (ActionState.PROPOSED, ActionState.FAILED),
        (ActionState.PROPOSED, ActionState.EXPIRED),
        (ActionState.AWAITING_APPROVAL, ActionState.AWAITING_CONFIRMATION),
        (ActionState.AWAITING_APPROVAL, ActionState.READY_TO_EXECUTE),
        (ActionState.AWAITING_APPROVAL, ActionState.REJECTED),
        (ActionState.AWAITING_APPROVAL, ActionState.EXPIRED),
        (ActionState.AWAITING_CONFIRMATION, ActionState.READY_TO_EXECUTE),
        (ActionState.AWAITING_CONFIRMATION, ActionState.REJECTED),
        (ActionState.AWAITING_CONFIRMATION, ActionState.EXPIRED),
        (ActionState.READY_TO_EXECUTE, ActionState.EXECUTING),
        (ActionState.READY_TO_EXECUTE, ActionState.POLICY_DENIED),
        (ActionState.READY_TO_EXECUTE, ActionState.EXPIRED),
        (ActionState.EXECUTING, ActionState.SUCCEEDED),
        (ActionState.EXECUTING, ActionState.FAILED),
        (ActionState.EXECUTING, ActionState.READY_TO_EXECUTE),
        (ActionState.EXECUTING, ActionState.UNRESOLVED),
        (ActionState.UNRESOLVED, ActionState.EXECUTING),
        (ActionState.UNRESOLVED, ActionState.SUCCEEDED),
        (ActionState.UNRESOLVED, ActionState.FAILED),
        (ActionState.UNRESOLVED, ActionState.UNRESOLVED),
    ],
)
def test_approved_lifecycle_edges_are_allowed(current: ActionState, target: ActionState) -> None:
    validate_action_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ActionState.PROPOSED, ActionState.EXECUTING),
        (ActionState.AWAITING_APPROVAL, ActionState.POLICY_DENIED),
        (ActionState.AWAITING_CONFIRMATION, ActionState.AWAITING_APPROVAL),
        (ActionState.READY_TO_EXECUTE, ActionState.SUCCEEDED),
        (ActionState.EXECUTING, ActionState.POLICY_DENIED),
        (ActionState.POLICY_DENIED, ActionState.PROPOSED),
        (ActionState.REJECTED, ActionState.READY_TO_EXECUTE),
        (ActionState.SUCCEEDED, ActionState.EXECUTING),
        (ActionState.FAILED, ActionState.READY_TO_EXECUTE),
        (ActionState.EXPIRED, ActionState.AWAITING_CONFIRMATION),
    ],
)
def test_unapproved_lifecycle_edges_are_rejected(current: ActionState, target: ActionState) -> None:
    with pytest.raises(InvalidActionTransitionError):
        validate_action_transition(current, target)


def _service(factory: FakeSessionFactory) -> ActionTransitionService:
    return ActionTransitionService(cast(async_sessionmaker[AsyncSession], factory))


@pytest.mark.asyncio
async def test_transition_updates_current_state_version_and_audit_event_together() -> None:
    context = action_context()
    request = action_request(trusted_context=context)
    session = FakeActionSession(scalar_values=[request], record=request)
    decision = PolicyDecision(
        allowed=True,
        reason_code="allowed",
        confirmation_required=True,
        approval_required=False,
        policy_version="stage6-policy-v1",
    )

    result = await _service(FakeSessionFactory(session)).transition(
        request.id,
        context.tenant_id,
        request.proposal_fingerprint,
        ActionState.AWAITING_CONFIRMATION,
        context.principal_id,
        ActionEventType.POLICY_ALLOWED,
        "allowed",
        policy_decision=decision,
    )

    assert result.state is ActionState.AWAITING_CONFIRMATION
    assert result.version == 2
    assert result.policy_allowed is True
    assert result.policy_reason_code == "allowed"
    assert result.policy_version == "stage6-policy-v1"
    assert result.confirmation_required is True
    assert result.approval_required is False
    events = [event for event in session.added if isinstance(event, ActionEvent)]
    assert len(events) == 1
    assert events[0].sequence == 2
    assert events[0].previous_state == ActionState.PROPOSED.value
    assert events[0].next_state == ActionState.AWAITING_CONFIRMATION.value


@pytest.mark.asyncio
async def test_transition_checks_tenant_fingerprint_and_persists_expiration() -> None:
    context = action_context()
    request = action_request(trusted_context=context)
    not_found_session = FakeActionSession(scalar_values=[None])
    with pytest.raises(ActionRequestNotFoundError):
        await _service(FakeSessionFactory(not_found_session)).transition(
            request.id,
            context.tenant_id,
            request.proposal_fingerprint,
            ActionState.AWAITING_CONFIRMATION,
            None,
            ActionEventType.STATE_TRANSITION,
            "test",
        )

    mismatch_session = FakeActionSession(scalar_values=[request], record=request)
    with pytest.raises(ProposalFingerprintMismatchError):
        await _service(FakeSessionFactory(mismatch_session)).transition(
            request.id,
            context.tenant_id,
            "0" * 64,
            ActionState.AWAITING_CONFIRMATION,
            None,
            ActionEventType.STATE_TRANSITION,
            "test",
        )

    expired_request = action_request(
        trusted_context=context,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    expired_session = FakeActionSession(scalar_values=[expired_request], record=expired_request)
    with pytest.raises(ActionExpiredError) as error:
        await _service(FakeSessionFactory(expired_session)).transition(
            expired_request.id,
            context.tenant_id,
            expired_request.proposal_fingerprint,
            ActionState.READY_TO_EXECUTE,
            context.principal_id,
            ActionEventType.STATE_TRANSITION,
            "ready",
        )

    assert error.value.record is not None
    assert error.value.record.state is ActionState.EXPIRED
    assert expired_request.version == 2
    assert [
        event.event_type for event in expired_session.added if hasattr(event, "event_type")
    ] == ["expired"]


@pytest.mark.asyncio
async def test_transition_persists_supervisor_then_customer_fingerprint_decisions() -> None:
    context = action_context()
    request = action_request(
        trusted_context=context,
        state=ActionState.AWAITING_APPROVAL,
        confirmation_required=True,
        approval_required=True,
    )
    request.policy_allowed = True
    request.policy_reason_code = "allowed"
    request.policy_version = "stage6-policy-v1"
    request.policy_observed_at = datetime.now(UTC)
    approval_session = FakeActionSession(scalar_values=[request], record=request)
    confirmation_session = FakeActionSession(scalar_values=[request], record=request)
    service = _service(FakeSessionFactory(approval_session, confirmation_session))

    approval = await service.transition(
        request.id,
        context.tenant_id,
        request.proposal_fingerprint,
        ActionState.AWAITING_CONFIRMATION,
        context.principal_id,
        ActionEventType.SUPERVISOR_APPROVED,
        "approved",
    )
    confirmation = await service.transition(
        request.id,
        context.tenant_id,
        request.proposal_fingerprint,
        ActionState.READY_TO_EXECUTE,
        context.principal_id,
        ActionEventType.CUSTOMER_CONFIRMED,
        "confirmed",
    )

    assert approval.supervisor_approval_decision == "approved"
    assert approval.supervisor_approval_actor_id == context.principal_id
    assert approval.supervisor_approval_fingerprint == request.proposal_fingerprint
    assert confirmation.customer_confirmation_decision == "confirmed"
    assert confirmation.customer_confirmation_actor_id == context.principal_id
    assert confirmation.customer_confirmation_fingerprint == request.proposal_fingerprint


@pytest.mark.asyncio
async def test_transition_requires_policy_gates_and_verified_success_evidence() -> None:
    context = action_context()
    proposed = action_request(trusted_context=context)
    no_policy_session = FakeActionSession(scalar_values=[proposed], record=proposed)
    with pytest.raises(ActionPolicyDecisionRequiredError):
        await _service(FakeSessionFactory(no_policy_session)).transition(
            proposed.id,
            context.tenant_id,
            proposed.proposal_fingerprint,
            ActionState.AWAITING_CONFIRMATION,
            context.principal_id,
            ActionEventType.STATE_TRANSITION,
            "allowed",
        )

    executing = action_request(trusted_context=context, state=ActionState.EXECUTING)
    missing_evidence_session = FakeActionSession(scalar_values=[executing], record=executing)
    with pytest.raises(InvalidActionTransitionError, match="verified read-back"):
        await _service(FakeSessionFactory(missing_evidence_session)).transition(
            executing.id,
            context.tenant_id,
            executing.proposal_fingerprint,
            ActionState.SUCCEEDED,
            context.principal_id,
            ActionEventType.VERIFICATION_SUCCEEDED,
            "verified",
        )

    verified_session = FakeActionSession(scalar_values=[executing], record=executing)
    resource_id = uuid4()
    succeeded = await _service(FakeSessionFactory(verified_session)).transition(
        executing.id,
        context.tenant_id,
        executing.proposal_fingerprint,
        ActionState.SUCCEEDED,
        context.principal_id,
        ActionEventType.VERIFICATION_SUCCEEDED,
        "verified",
        verified_resource_id=resource_id,
    )
    assert succeeded.state is ActionState.SUCCEEDED
    assert succeeded.verification_status == "verified"
    assert succeeded.verified_resource_id == resource_id
    assert succeeded.verified_at is not None
