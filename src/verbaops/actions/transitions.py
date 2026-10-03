"""Serialized, audited mutations for durable action requests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from verbaops.actions.models import ActionState, ActionType
from verbaops.actions.persistence import ActionEvent, ActionRequest
from verbaops.actions.policy import PolicyDecision


class ActionEventType(StrEnum):
    """Bounded event labels stored in the action audit log."""

    CREATED = "created"
    POLICY_ALLOWED = "policy_allowed"
    POLICY_DENIED = "policy_denied"
    CUSTOMER_CONFIRMED = "customer_confirmed"
    CUSTOMER_REJECTED = "customer_rejected"
    SUPERVISOR_APPROVED = "supervisor_approved"
    SUPERVISOR_REJECTED = "supervisor_rejected"
    EXECUTION_STARTED = "execution_started"
    COMMERCE_RESPONSE = "commerce_response"
    VERIFICATION_SUCCEEDED = "verification_succeeded"
    VERIFICATION_FAILED = "verification_failed"
    UNRESOLVED = "unresolved"
    EXPIRED = "expired"
    STATE_TRANSITION = "state_transition"


_ALLOWED_TRANSITIONS: dict[ActionState, frozenset[ActionState]] = {
    ActionState.PROPOSED: frozenset(
        {
            ActionState.POLICY_DENIED,
            ActionState.AWAITING_APPROVAL,
            ActionState.AWAITING_CONFIRMATION,
            ActionState.READY_TO_EXECUTE,
            ActionState.FAILED,
            ActionState.EXPIRED,
        }
    ),
    ActionState.POLICY_DENIED: frozenset(),
    ActionState.AWAITING_APPROVAL: frozenset(
        {
            ActionState.AWAITING_CONFIRMATION,
            ActionState.READY_TO_EXECUTE,
            ActionState.REJECTED,
            ActionState.EXPIRED,
        }
    ),
    ActionState.AWAITING_CONFIRMATION: frozenset(
        {ActionState.READY_TO_EXECUTE, ActionState.REJECTED, ActionState.EXPIRED}
    ),
    ActionState.READY_TO_EXECUTE: frozenset(
        {ActionState.EXECUTING, ActionState.POLICY_DENIED, ActionState.EXPIRED}
    ),
    ActionState.EXECUTING: frozenset(
        {
            ActionState.SUCCEEDED,
            ActionState.FAILED,
            ActionState.READY_TO_EXECUTE,
            ActionState.UNRESOLVED,
        }
    ),
    ActionState.SUCCEEDED: frozenset(),
    ActionState.REJECTED: frozenset(),
    ActionState.FAILED: frozenset(),
    ActionState.UNRESOLVED: frozenset(
        {
            ActionState.EXECUTING,
            ActionState.SUCCEEDED,
            ActionState.FAILED,
            ActionState.UNRESOLVED,
        }
    ),
    ActionState.EXPIRED: frozenset(),
}
_UNDISPATCHED_STATES = frozenset(
    {
        ActionState.PROPOSED,
        ActionState.AWAITING_APPROVAL,
        ActionState.AWAITING_CONFIRMATION,
        ActionState.READY_TO_EXECUTE,
    }
)
_REASON_CODE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")


class ActionTransitionError(RuntimeError):
    """Base class for rejected action lifecycle changes."""


class InvalidActionTransitionError(ActionTransitionError):
    """The requested state edge is not in the approved lifecycle graph."""


class ActionRequestNotFoundError(ActionTransitionError):
    """No action request exists in the supplied tenant scope."""


class ProposalFingerprintMismatchError(ActionTransitionError):
    """The caller's proposal fingerprint no longer matches the stored request."""


class ActionExpiredError(ActionTransitionError):
    """An undispatched request expired before the requested transition."""

    def __init__(self, record: ActionRequestRecord | None = None) -> None:
        super().__init__("action request has expired")
        self.record = record


class ActionPolicyDecisionRequiredError(ActionTransitionError):
    """An initial allowed or denied policy decision was not persisted with the transition."""


class ConcurrentActionUpdateError(ActionTransitionError):
    """The locked row's version changed before its conditional update."""


@dataclass(frozen=True, slots=True)
class ActionRequestRecord:
    """Detached, typed snapshot returned from repository and transition operations."""

    id: UUID
    tenant_id: UUID
    customer_id: UUID
    proposing_principal_id: UUID
    conversation_id: UUID
    agent_run_id: UUID
    originating_tool_invocation_id: UUID | None
    action_type: ActionType
    proposal_payload: dict[str, Any]
    target_ids: tuple[UUID, ...]
    proposal_schema_version: str
    proposal_fingerprint: str
    state: ActionState
    policy_allowed: bool | None
    policy_reason_code: str | None
    policy_version: str | None
    policy_observed_at: datetime | None
    confirmation_required: bool
    approval_required: bool
    customer_confirmation_decision: str | None
    customer_confirmation_actor_id: UUID | None
    customer_confirmation_at: datetime | None
    customer_confirmation_fingerprint: str | None
    supervisor_approval_decision: str | None
    supervisor_approval_actor_id: UUID | None
    supervisor_approval_at: datetime | None
    supervisor_approval_fingerprint: str | None
    idempotency_key: UUID
    expires_at: datetime
    execution_attempt_count: int
    execution_lease_owner: UUID | None
    execution_lease_expires_at: datetime | None
    commerce_resource_id: UUID | None
    commerce_status_code: int | None
    commerce_error_code: str | None
    verification_status: str | None
    verified_resource_id: UUID | None
    verified_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime


def validate_action_transition(current: ActionState, target: ActionState) -> None:
    """Reject any lifecycle edge not explicitly approved for Stage 6."""

    try:
        current_state = ActionState(current)
        target_state = ActionState(target)
    except ValueError as error:
        raise InvalidActionTransitionError("unknown action lifecycle state") from error
    if target_state not in _ALLOWED_TRANSITIONS[current_state]:
        raise InvalidActionTransitionError(
            f"action cannot transition from {current_state.value} to {target_state.value}"
        )


def action_request_record(request: ActionRequest) -> ActionRequestRecord:
    """Convert an ORM row to a detached immutable domain snapshot."""

    return ActionRequestRecord(
        id=request.id,
        tenant_id=request.tenant_id,
        customer_id=request.customer_id,
        proposing_principal_id=request.proposing_principal_id,
        conversation_id=request.conversation_id,
        agent_run_id=request.agent_run_id,
        originating_tool_invocation_id=request.originating_tool_invocation_id,
        action_type=ActionType(request.action_type),
        proposal_payload=dict(request.proposal_payload),
        target_ids=tuple(UUID(target_id) for target_id in request.target_ids),
        proposal_schema_version=request.proposal_schema_version,
        proposal_fingerprint=request.proposal_fingerprint,
        state=ActionState(request.state),
        policy_allowed=request.policy_allowed,
        policy_reason_code=request.policy_reason_code,
        policy_version=request.policy_version,
        policy_observed_at=request.policy_observed_at,
        confirmation_required=request.confirmation_required,
        approval_required=request.approval_required,
        customer_confirmation_decision=request.customer_confirmation_decision,
        customer_confirmation_actor_id=request.customer_confirmation_actor_id,
        customer_confirmation_at=request.customer_confirmation_at,
        customer_confirmation_fingerprint=request.customer_confirmation_fingerprint,
        supervisor_approval_decision=request.supervisor_approval_decision,
        supervisor_approval_actor_id=request.supervisor_approval_actor_id,
        supervisor_approval_at=request.supervisor_approval_at,
        supervisor_approval_fingerprint=request.supervisor_approval_fingerprint,
        idempotency_key=request.idempotency_key,
        expires_at=request.expires_at,
        execution_attempt_count=request.execution_attempt_count,
        execution_lease_owner=request.execution_lease_owner,
        execution_lease_expires_at=request.execution_lease_expires_at,
        commerce_resource_id=request.commerce_resource_id,
        commerce_status_code=request.commerce_status_code,
        commerce_error_code=request.commerce_error_code,
        verification_status=request.verification_status,
        verified_resource_id=request.verified_resource_id,
        verified_at=request.verified_at,
        version=request.version,
        created_at=request.created_at,
        updated_at=request.updated_at,
    )


async def _transition_locked(
    session: AsyncSession,
    request: ActionRequest,
    *,
    target_state: ActionState,
    actor_id: UUID | None,
    event_type: ActionEventType,
    reason_code: str | None,
    policy_decision: PolicyDecision | None = None,
    verified_resource_id: UUID | None = None,
    now: datetime | None = None,
) -> tuple[ActionRequest, bool]:
    """Apply the one authoritative row-and-event mutation inside a caller transaction."""

    current = ActionState(request.state)
    observed_at = now or datetime.now(UTC)
    expired_before_target = False

    if current is ActionState.EXPIRED:
        return request, True
    if current in _UNDISPATCHED_STATES and request.expires_at <= observed_at:
        target_state = ActionState.EXPIRED
        event_type = ActionEventType.EXPIRED
        reason_code = "expired"
        policy_decision = None
        expired_before_target = True
    else:
        validate_action_transition(current, target_state)
    if (
        current is ActionState.EXECUTING
        and target_state is ActionState.READY_TO_EXECUTE
        and reason_code != "proven_non_dispatch"
    ):
        raise InvalidActionTransitionError(
            "execution may return to ready only after a proven non-dispatch result"
        )

    if reason_code is not None and not _REASON_CODE.fullmatch(reason_code):
        raise ValueError("action event reason must be a bounded reason code")
    if event_type is ActionEventType.CREATED:
        raise ValueError("created is emitted only when an action request is inserted")
    if target_state is ActionState.EXPIRED and event_type is not ActionEventType.EXPIRED:
        raise ValueError("expired state requires the expired event type")
    if (
        target_state is ActionState.POLICY_DENIED
        and event_type is not ActionEventType.POLICY_DENIED
    ):
        raise ValueError("policy_denied state requires the policy_denied event type")
    if target_state is ActionState.UNRESOLVED and event_type is not ActionEventType.UNRESOLVED:
        raise ValueError("unresolved state requires the unresolved event type")
    if target_state is ActionState.SUCCEEDED:
        if event_type is not ActionEventType.VERIFICATION_SUCCEEDED or verified_resource_id is None:
            raise InvalidActionTransitionError(
                "success requires verified read-back evidence for the resulting resource"
            )
    elif verified_resource_id is not None:
        raise ValueError("verified resource evidence is only accepted with succeeded state")
    if (
        event_type is ActionEventType.VERIFICATION_SUCCEEDED
        and target_state is not ActionState.SUCCEEDED
    ):
        raise InvalidActionTransitionError("verification success must target succeeded state")
    if policy_decision is not None:
        expected_event = (
            ActionEventType.POLICY_ALLOWED
            if policy_decision.allowed
            else ActionEventType.POLICY_DENIED
        )
        if event_type is not expected_event:
            raise ValueError("policy decision and audit event type must agree")
        if policy_decision.allowed and target_state not in {
            ActionState.AWAITING_APPROVAL,
            ActionState.AWAITING_CONFIRMATION,
            ActionState.READY_TO_EXECUTE,
        }:
            raise ValueError("allowed policy must select an executable gate state")
        if not policy_decision.allowed and target_state is not ActionState.POLICY_DENIED:
            raise ValueError("denied policy must select policy_denied")
        if policy_decision.allowed:
            if policy_decision.approval_required:
                expected_state = ActionState.AWAITING_APPROVAL
            elif policy_decision.confirmation_required:
                expected_state = ActionState.AWAITING_CONFIRMATION
            else:
                expected_state = ActionState.READY_TO_EXECUTE
            if target_state is not expected_state:
                raise ValueError("allowed policy must select the state for its required gates")
    elif event_type in {ActionEventType.POLICY_ALLOWED, ActionEventType.POLICY_DENIED}:
        raise ValueError("policy audit events require the complete policy decision")

    if (
        request.policy_allowed is None
        and target_state
        in {
            ActionState.AWAITING_APPROVAL,
            ActionState.AWAITING_CONFIRMATION,
            ActionState.READY_TO_EXECUTE,
        }
        and policy_decision is None
    ):
        raise ActionPolicyDecisionRequiredError(
            "the first allowed transition must persist policy and gate metadata"
        )

    previous_version = request.version
    next_version = previous_version + 1
    values: dict[str, Any] = {
        "state": target_state.value,
        "version": next_version,
        "updated_at": observed_at,
    }
    if policy_decision is not None:
        values.update(
            {
                "policy_allowed": policy_decision.allowed,
                "policy_reason_code": policy_decision.reason_code,
                "policy_version": policy_decision.policy_version,
                "policy_observed_at": observed_at,
                "confirmation_required": policy_decision.confirmation_required,
                "approval_required": policy_decision.approval_required,
            }
        )
    if target_state is ActionState.SUCCEEDED:
        values.update(
            {
                "verification_status": "verified",
                "verified_resource_id": verified_resource_id,
                "verified_at": observed_at,
            }
        )

    current_state = ActionState(request.state)
    if current_state is ActionState.AWAITING_APPROVAL and target_state in {
        ActionState.AWAITING_CONFIRMATION,
        ActionState.READY_TO_EXECUTE,
        ActionState.REJECTED,
    }:
        if not request.approval_required:
            raise InvalidActionTransitionError("action has no supervisor approval gate")
        if target_state is ActionState.REJECTED:
            expected_event = ActionEventType.SUPERVISOR_REJECTED
            decision = "rejected"
        else:
            expected_event = ActionEventType.SUPERVISOR_APPROVED
            decision = "approved"
            expected_state = (
                ActionState.AWAITING_CONFIRMATION
                if request.confirmation_required
                else ActionState.READY_TO_EXECUTE
            )
            if target_state is not expected_state:
                raise InvalidActionTransitionError(
                    "supervisor approval must preserve the customer confirmation gate"
                )
        if event_type is not expected_event or actor_id is None:
            raise InvalidActionTransitionError("supervisor decision requires its event and actor")
        values.update(
            {
                "supervisor_approval_decision": decision,
                "supervisor_approval_actor_id": actor_id,
                "supervisor_approval_at": observed_at,
                "supervisor_approval_fingerprint": request.proposal_fingerprint,
            }
        )

    if current_state is ActionState.AWAITING_CONFIRMATION and target_state in {
        ActionState.READY_TO_EXECUTE,
        ActionState.REJECTED,
    }:
        if not request.confirmation_required:
            raise InvalidActionTransitionError("action has no customer confirmation gate")
        expected_event = (
            ActionEventType.CUSTOMER_CONFIRMED
            if target_state is ActionState.READY_TO_EXECUTE
            else ActionEventType.CUSTOMER_REJECTED
        )
        decision = "confirmed" if target_state is ActionState.READY_TO_EXECUTE else "rejected"
        if event_type is not expected_event or actor_id is None:
            raise InvalidActionTransitionError("customer decision requires its event and actor")
        values.update(
            {
                "customer_confirmation_decision": decision,
                "customer_confirmation_actor_id": actor_id,
                "customer_confirmation_at": observed_at,
                "customer_confirmation_fingerprint": request.proposal_fingerprint,
            }
        )
    if event_type in {
        ActionEventType.SUPERVISOR_APPROVED,
        ActionEventType.SUPERVISOR_REJECTED,
    } and not (
        current_state is ActionState.AWAITING_APPROVAL
        and target_state
        in {
            ActionState.AWAITING_CONFIRMATION,
            ActionState.READY_TO_EXECUTE,
            ActionState.REJECTED,
        }
    ):
        raise InvalidActionTransitionError(
            "supervisor event is not attached to an approval transition"
        )
    if event_type in {
        ActionEventType.CUSTOMER_CONFIRMED,
        ActionEventType.CUSTOMER_REJECTED,
    } and not (
        current_state is ActionState.AWAITING_CONFIRMATION
        and target_state in {ActionState.READY_TO_EXECUTE, ActionState.REJECTED}
    ):
        raise InvalidActionTransitionError(
            "customer event is not attached to a confirmation transition"
        )

    result = await session.execute(
        update(ActionRequest)
        .where(
            ActionRequest.id == request.id,
            ActionRequest.tenant_id == request.tenant_id,
            ActionRequest.version == previous_version,
            ActionRequest.state == current.value,
        )
        .values(**values)
        .returning(ActionRequest.id)
    )
    if result.scalar_one_or_none() is None:
        raise ConcurrentActionUpdateError("action request changed while locked")

    session.add(
        ActionEvent(
            id=uuid4(),
            action_request_id=request.id,
            tenant_id=request.tenant_id,
            sequence=next_version,
            event_type=event_type.value,
            actor_principal_id=actor_id,
            previous_state=current.value,
            next_state=target_state.value,
            proposal_fingerprint=request.proposal_fingerprint,
            reason_code=reason_code,
        )
    )
    await session.flush()
    await session.refresh(request)
    return request, expired_before_target


class ActionTransitionService:
    """Validate and atomically persist one lifecycle state change and audit event."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def transition(
        self,
        action_request_id: UUID,
        tenant_id: UUID,
        expected_fingerprint: str,
        target_state: ActionState,
        actor_id: UUID | None,
        event_type: ActionEventType,
        reason_code: str | None,
        *,
        policy_decision: PolicyDecision | None = None,
        verified_resource_id: UUID | None = None,
    ) -> ActionRequestRecord:
        """Lock, validate, and record one tenant-scoped action transition."""

        request_record: ActionRequestRecord | None = None
        expiration_rejected = False
        async with self._session_factory() as session, session.begin():
            request = await session.scalar(
                select(ActionRequest)
                .where(
                    ActionRequest.id == action_request_id,
                    ActionRequest.tenant_id == tenant_id,
                )
                .with_for_update()
            )
            if request is None:
                raise ActionRequestNotFoundError("action request not found in tenant scope")
            if request.proposal_fingerprint != expected_fingerprint:
                raise ProposalFingerprintMismatchError("proposal fingerprint does not match")
            request, expiration_rejected = await _transition_locked(
                session,
                request,
                target_state=target_state,
                actor_id=actor_id,
                event_type=event_type,
                reason_code=reason_code,
                policy_decision=policy_decision,
                verified_resource_id=verified_resource_id,
            )
            request_record = action_request_record(request)
        if request_record is None:
            raise RuntimeError("action transition did not produce a request record")
        if expiration_rejected:
            raise ActionExpiredError(request_record)
        return request_record
