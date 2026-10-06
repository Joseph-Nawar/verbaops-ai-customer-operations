"""Transaction-owning creation, deduplication, and supersession for action requests."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from verbaops.actions.models import ActionProposal, ActionState, proposal_target_ids
from verbaops.actions.persistence import ActionEvent, ActionRequest
from verbaops.actions.transitions import (
    ActionEventType,
    ActionRequestRecord,
    _transition_locked,
    action_request_record,
)
from verbaops.auth.context import TrustedContext
from verbaops.conversations.persistence import AgentRun, Conversation, ToolInvocation

_SCHEMA_VERSION = "action-proposal-v1"
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_ACTIVE_STATES = tuple(
    state.value
    for state in (
        ActionState.PROPOSED,
        ActionState.AWAITING_APPROVAL,
        ActionState.AWAITING_CONFIRMATION,
        ActionState.READY_TO_EXECUTE,
        ActionState.EXECUTING,
        ActionState.UNRESOLVED,
    )
)
_UNDISPATCHED_STATES = frozenset(
    {
        ActionState.PROPOSED,
        ActionState.AWAITING_APPROVAL,
        ActionState.AWAITING_CONFIRMATION,
        ActionState.READY_TO_EXECUTE,
    }
)

__all__ = ["ActionRepository", "ActionRequestRecord"]


class ActionRepositoryError(RuntimeError):
    """Base class for rejected action creation requests."""


class ActionScopeError(ActionRepositoryError):
    """Trusted context, conversation, run, and invocation do not share scope."""


class ActionOriginConflictError(ActionRepositoryError):
    """The durable invocation is bound to another scope or different action material."""


class ActionInFlightError(ActionRepositoryError):
    """A changed proposal cannot replace an action whose dispatch is unresolved."""


class ProposalFingerprintCollisionError(ActionRepositoryError):
    """One fingerprint was supplied for different normalized proposal material."""


class ActionRequestRecordConflictError(ActionRepositoryError):
    """A uniqueness conflict occurred without a scoped winning request to load."""


def _proposal_payload(proposal: ActionProposal) -> dict[str, Any]:
    if not isinstance(proposal, BaseModel):
        raise TypeError("proposal must be a validated action model")
    return proposal.model_dump(mode="json")


def _same_proposal(
    request: ActionRequest,
    *,
    action_type: str,
    payload: dict[str, Any],
    target_ids: list[str],
    fingerprint: str,
) -> bool:
    if request.proposal_fingerprint != fingerprint:
        return False
    if (
        request.action_type != action_type
        or request.proposal_payload != payload
        or request.target_ids != target_ids
    ):
        raise ProposalFingerprintCollisionError(
            "proposal fingerprint does not describe the stored action material"
        )
    return True


class ActionRepository:
    """Create, deduplicate, and supersede requests in tenant-scoped transactions."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_active_for_conversation(
        self, *, tenant_id: UUID, customer_id: UUID, conversation_id: UUID
    ) -> list[ActionRequestRecord]:
        """Load only active action requests for one trusted conversation scope."""

        async with self._session_factory() as session, session.begin():
            rows = await session.scalars(
                select(ActionRequest)
                .where(
                    ActionRequest.tenant_id == tenant_id,
                    ActionRequest.customer_id == customer_id,
                    ActionRequest.conversation_id == conversation_id,
                    ActionRequest.state.in_(_ACTIVE_STATES),
                )
                .order_by(ActionRequest.created_at, ActionRequest.id)
            )
            return [action_request_record(row) for row in rows]

    async def create_or_get(
        self,
        *,
        trusted_context: TrustedContext,
        conversation_id: UUID,
        agent_run_id: UUID,
        tool_invocation_id: UUID,
        proposal: ActionProposal,
        proposal_fingerprint: str,
        expires_at: datetime,
    ) -> tuple[ActionRequestRecord, bool]:
        """Insert a proposed request and event, or load its scoped idempotent winner."""

        if trusted_context.customer_id is None:
            raise ActionScopeError("action creation requires a trusted customer binding")
        if not _FINGERPRINT.fullmatch(proposal_fingerprint):
            raise ValueError("proposal fingerprint must be lowercase SHA-256 hex")
        payload = _proposal_payload(proposal)
        target_ids = proposal_target_ids(proposal)
        target_values = [str(target_id) for target_id in target_ids]
        action_type = str(payload["action_type"])

        try:
            async with self._session_factory() as session, session.begin():
                conversation = await session.scalar(
                    select(Conversation)
                    .where(
                        Conversation.id == conversation_id,
                        Conversation.tenant_id == trusted_context.tenant_id,
                        Conversation.customer_id == trusted_context.customer_id,
                    )
                    .with_for_update()
                )
                if conversation is None:
                    raise ActionScopeError(
                        "conversation is outside the trusted tenant/customer scope"
                    )
                run_exists = await session.scalar(
                    select(AgentRun.id).where(
                        AgentRun.id == agent_run_id,
                        AgentRun.conversation_id == conversation_id,
                    )
                )
                if run_exists is None:
                    raise ActionScopeError("agent run does not belong to the scoped conversation")
                invocation_exists = await session.scalar(
                    select(ToolInvocation.id).where(
                        ToolInvocation.id == tool_invocation_id,
                        ToolInvocation.agent_run_id == agent_run_id,
                    )
                )
                if invocation_exists is None:
                    raise ActionScopeError(
                        "tool invocation does not belong to the scoped agent run"
                    )

                origin_request = await session.scalar(
                    select(ActionRequest).where(
                        ActionRequest.originating_tool_invocation_id == tool_invocation_id
                    )
                )
                if origin_request is not None:
                    self._validate_origin_scope(
                        origin_request,
                        trusted_context=trusted_context,
                        conversation_id=conversation_id,
                        agent_run_id=agent_run_id,
                    )
                    self._validate_origin_material(
                        origin_request,
                        action_type=action_type,
                        payload=payload,
                        target_ids=target_values,
                        fingerprint=proposal_fingerprint,
                    )
                    return action_request_record(origin_request), False

                active_request = await session.scalar(
                    select(ActionRequest)
                    .where(
                        ActionRequest.tenant_id == trusted_context.tenant_id,
                        ActionRequest.conversation_id == conversation_id,
                        ActionRequest.customer_id == trusted_context.customer_id,
                        ActionRequest.proposal_fingerprint == proposal_fingerprint,
                        ActionRequest.state.in_(_ACTIVE_STATES),
                    )
                    .with_for_update()
                )
                if active_request is not None:
                    _same_proposal(
                        active_request,
                        action_type=action_type,
                        payload=payload,
                        target_ids=target_values,
                        fingerprint=proposal_fingerprint,
                    )
                    return action_request_record(active_request), False

                now = datetime.now(UTC)
                if expires_at.tzinfo is None or expires_at.utcoffset() is None:
                    raise ValueError("action expiry must be timezone-aware")
                if expires_at <= now:
                    raise ValueError("new action expiry must be in the future")

                prior_requests = (
                    await session.scalars(
                        select(ActionRequest)
                        .where(
                            ActionRequest.tenant_id == trusted_context.tenant_id,
                            ActionRequest.conversation_id == conversation_id,
                            ActionRequest.customer_id == trusted_context.customer_id,
                            ActionRequest.action_type == action_type,
                            ActionRequest.target_ids == target_values,
                            ActionRequest.state.in_(_ACTIVE_STATES),
                        )
                        .order_by(ActionRequest.created_at, ActionRequest.id)
                        .with_for_update()
                    )
                ).all()
                for prior in prior_requests:
                    prior_state = ActionState(prior.state)
                    if prior.proposal_fingerprint == proposal_fingerprint:
                        _same_proposal(
                            prior,
                            action_type=action_type,
                            payload=payload,
                            target_ids=target_values,
                            fingerprint=proposal_fingerprint,
                        )
                        return action_request_record(prior), False
                    if prior_state not in _UNDISPATCHED_STATES:
                        raise ActionInFlightError(
                            "a dispatched or unresolved action for these targets remains active"
                        )
                    await _transition_locked(
                        session,
                        prior,
                        target_state=ActionState.EXPIRED,
                        actor_id=trusted_context.principal_id,
                        event_type=ActionEventType.EXPIRED,
                        reason_code="superseded",
                    )

                request = ActionRequest(
                    id=uuid4(),
                    tenant_id=trusted_context.tenant_id,
                    customer_id=trusted_context.customer_id,
                    proposing_principal_id=trusted_context.principal_id,
                    conversation_id=conversation_id,
                    agent_run_id=agent_run_id,
                    originating_tool_invocation_id=tool_invocation_id,
                    action_type=action_type,
                    proposal_payload=payload,
                    target_ids=target_values,
                    proposal_schema_version=_SCHEMA_VERSION,
                    proposal_fingerprint=proposal_fingerprint,
                    state=ActionState.PROPOSED.value,
                    idempotency_key=uuid4(),
                    expires_at=expires_at,
                )
                session.add(request)
                await session.flush()
                session.add(
                    ActionEvent(
                        id=uuid4(),
                        action_request_id=request.id,
                        tenant_id=request.tenant_id,
                        sequence=1,
                        event_type=ActionEventType.CREATED.value,
                        actor_principal_id=trusted_context.principal_id,
                        previous_state=None,
                        next_state=ActionState.PROPOSED.value,
                        proposal_fingerprint=proposal_fingerprint,
                        correlation_id=tool_invocation_id,
                        reason_code=None,
                    )
                )
                await session.flush()
                await session.refresh(request)
                created_record = action_request_record(request)
            return created_record, True
        except IntegrityError as error:
            winner = await self._load_unique_winner(
                trusted_context=trusted_context,
                conversation_id=conversation_id,
                agent_run_id=agent_run_id,
                tool_invocation_id=tool_invocation_id,
                action_type=action_type,
                payload=payload,
                target_ids=target_values,
                fingerprint=proposal_fingerprint,
            )
            if winner is None:
                raise ActionRequestRecordConflictError(
                    "action creation conflicted without a scoped winning request"
                ) from error
            return winner, False

    @staticmethod
    def _validate_origin_scope(
        request: ActionRequest,
        *,
        trusted_context: TrustedContext,
        conversation_id: UUID,
        agent_run_id: UUID,
    ) -> None:
        if (
            request.tenant_id != trusted_context.tenant_id
            or request.customer_id != trusted_context.customer_id
            or request.conversation_id != conversation_id
            or request.agent_run_id != agent_run_id
        ):
            raise ActionOriginConflictError(
                "durable tool invocation is already attached to an action in another scope"
            )

    @staticmethod
    def _validate_origin_material(
        request: ActionRequest,
        *,
        action_type: str,
        payload: dict[str, Any],
        target_ids: list[str],
        fingerprint: str,
    ) -> None:
        message = "durable tool invocation is already attached to different action material"
        try:
            same_proposal = _same_proposal(
                request,
                action_type=action_type,
                payload=payload,
                target_ids=target_ids,
                fingerprint=fingerprint,
            )
        except ProposalFingerprintCollisionError as error:
            raise ActionOriginConflictError(message) from error
        if not same_proposal:
            raise ActionOriginConflictError(message)

    async def _load_unique_winner(
        self,
        *,
        trusted_context: TrustedContext,
        conversation_id: UUID,
        agent_run_id: UUID,
        tool_invocation_id: UUID,
        action_type: str,
        payload: dict[str, Any],
        target_ids: list[str],
        fingerprint: str,
    ) -> ActionRequestRecord | None:
        """Resolve an external unique-index race to its committed scoped winner."""

        async with self._session_factory() as session:
            origin_request = await session.scalar(
                select(ActionRequest).where(
                    ActionRequest.originating_tool_invocation_id == tool_invocation_id
                )
            )
            if origin_request is not None:
                self._validate_origin_scope(
                    origin_request,
                    trusted_context=trusted_context,
                    conversation_id=conversation_id,
                    agent_run_id=agent_run_id,
                )
                self._validate_origin_material(
                    origin_request,
                    action_type=action_type,
                    payload=payload,
                    target_ids=target_ids,
                    fingerprint=fingerprint,
                )
                return action_request_record(origin_request)

            active_request = await session.scalar(
                select(ActionRequest).where(
                    ActionRequest.tenant_id == trusted_context.tenant_id,
                    ActionRequest.conversation_id == conversation_id,
                    ActionRequest.customer_id == trusted_context.customer_id,
                    ActionRequest.proposal_fingerprint == fingerprint,
                    ActionRequest.state.in_(_ACTIVE_STATES),
                )
            )
            if active_request is None:
                return None
            _same_proposal(
                active_request,
                action_type=action_type,
                payload=payload,
                target_ids=target_ids,
                fingerprint=fingerprint,
            )
            return action_request_record(active_request)
