"""Trusted customer confirmation and withdrawal for durable action requests."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

from verbaops.actions.executor import ActionExecutor
from verbaops.actions.models import (
    ActionProposal,
    ActionState,
    ActionType,
    CancelOrderProposal,
    RefundProposal,
    RescheduleDeliveryProposal,
    ReturnProposal,
    SupportTicketProposal,
    parse_action_proposal_payload,
)
from verbaops.actions.proposals import ActionProposalService
from verbaops.actions.transitions import (
    ActionEventType,
    ActionExpiredError,
    ActionRequestRecord,
    ActionTransitionService,
    ConcurrentActionUpdateError,
    InvalidActionTransitionError,
    ProposalFingerprintMismatchError,
)
from verbaops.auth.context import TrustedContext, has_customer_authority
from verbaops.commerce.client import CommerceClient
from verbaops.commerce.errors import CommerceError


class ActionDecisionConflictError(RuntimeError):
    """The requested decision does not match the current durable action state."""


class ActionDecisionForbiddenError(PermissionError):
    """Only the owning customer principal may decide a customer action."""


class ActionFreshnessUnavailableError(RuntimeError):
    """Current Commerce facts could not be read safely before confirmation."""


class ActionRequestView(BaseModel):
    """Small customer-safe projection of the durable action request."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    action_request_id: UUID
    action_type: ActionType
    state: ActionState
    proposal_fingerprint: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    proposal: ActionProposal
    safe_summary: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    currency_code: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")] | None = None
    required_next_actor: Literal["customer", "support_supervisor", "none"]
    expires_at: datetime
    customer_decision: Literal["confirmed", "rejected"] | None
    result_status: Literal["verified", "mismatched", "unavailable"] | None


class ActionDecisionService:
    """Apply customer decisions after trusted scope and confirmation-time freshness checks."""

    def __init__(
        self,
        *,
        transition_service: ActionTransitionService,
        freshness_service: ActionProposalService,
        action_executor: ActionExecutor,
        commerce_client: CommerceClient,
    ) -> None:
        self._transitions = transition_service
        self._freshness = freshness_service
        self._executor = action_executor
        self._commerce = commerce_client

    async def get_action_request(
        self, action_request_id: UUID, trusted_context: TrustedContext
    ) -> ActionRequestView:
        """Return a customer-safe action view inside the authenticated owner scope."""

        self._require_customer_context(trusted_context)
        record = await self._get_scoped(action_request_id, trusted_context)
        currency_code: str | None = None
        if record.action_type is ActionType.REQUEST_REFUND and ActionState(record.state) in {
            ActionState.AWAITING_CONFIRMATION,
            ActionState.AWAITING_APPROVAL,
        }:
            try:
                currency = await self._commerce.get_tenant_currency()
            except CommerceError:
                currency = None
            currency_code = currency.currency_code if currency is not None else None
        return self.view(record, currency_code=currency_code)

    async def confirm(
        self,
        action_request_id: UUID,
        trusted_context: TrustedContext,
        proposal_fingerprint: str,
    ) -> ActionRequestView:
        """Freshly validate and bind customer confirmation before internal execution."""

        self._require_customer_context(trusted_context)
        record = await self._get_scoped(action_request_id, trusted_context)
        self._require_fingerprint(record, proposal_fingerprint)
        state = ActionState(record.state)

        if _same_customer_decision(record, "confirmed", proposal_fingerprint):
            if state is ActionState.READY_TO_EXECUTE and _decision_gates_satisfied(record):
                record = await self._executor.execute_ready(record.id)
            return self.view(record)
        if state is ActionState.AWAITING_APPROVAL:
            raise ActionDecisionConflictError("action decision conflicts with current state")
        if state is not ActionState.AWAITING_CONFIRMATION:
            raise ActionDecisionConflictError("action decision conflicts with current state")

        try:
            freshness = await self._freshness.refresh(record)
        except CommerceError:
            raise ActionFreshnessUnavailableError("current action facts are unavailable") from None
        decision = freshness.policy_decision
        currency_code = (
            freshness.canonical_currency
            if record.action_type is ActionType.REQUEST_REFUND
            else None
        )
        if (
            freshness.proposal_fingerprint != record.proposal_fingerprint
            or not decision.allowed
            or not decision.confirmation_required
            or decision.approval_required != record.approval_required
            or (
                record.approval_required
                and (
                    record.supervisor_approval_decision != "approved"
                    or record.supervisor_approval_fingerprint != record.proposal_fingerprint
                )
            )
        ):
            current = await self._expire_stale(record, trusted_context)
            if _same_customer_decision(current, "confirmed", proposal_fingerprint):
                if ActionState(
                    current.state
                ) is ActionState.READY_TO_EXECUTE and _decision_gates_satisfied(current):
                    current = await self._executor.execute_ready(current.id)
                return self.view(current, currency_code=currency_code)
            raise ActionDecisionConflictError("action decision conflicts with current state")

        try:
            record = await self._transitions.transition(
                record.id,
                record.tenant_id,
                record.proposal_fingerprint,
                ActionState.READY_TO_EXECUTE,
                trusted_context.principal_id,
                ActionEventType.CUSTOMER_CONFIRMED,
                None,
            )
        except (
            ActionExpiredError,
            ConcurrentActionUpdateError,
            InvalidActionTransitionError,
            ProposalFingerprintMismatchError,
        ):
            current = await self._get_scoped(action_request_id, trusted_context)
            if _same_customer_decision(current, "confirmed", proposal_fingerprint):
                if ActionState(
                    current.state
                ) is ActionState.READY_TO_EXECUTE and _decision_gates_satisfied(current):
                    current = await self._executor.execute_ready(current.id)
                return self.view(current, currency_code=currency_code)
            raise ActionDecisionConflictError(
                "action decision conflicts with current state"
            ) from None

        # transition() commits the decision and its event before the executor starts I/O.
        if ActionState(record.state) is ActionState.READY_TO_EXECUTE and _decision_gates_satisfied(
            record
        ):
            record = await self._executor.execute_ready(record.id)
        return self.view(record, currency_code=currency_code)

    async def reject(
        self,
        action_request_id: UUID,
        trusted_context: TrustedContext,
        proposal_fingerprint: str,
    ) -> ActionRequestView:
        """Withdraw a pending customer proposal without running Commerce writes."""

        self._require_customer_context(trusted_context)
        record = await self._get_scoped(action_request_id, trusted_context)
        self._require_fingerprint(record, proposal_fingerprint)
        if _same_customer_decision(record, "rejected", proposal_fingerprint):
            return self.view(record)
        if ActionState(record.state) not in {
            ActionState.AWAITING_CONFIRMATION,
            ActionState.AWAITING_APPROVAL,
        }:
            raise ActionDecisionConflictError("action decision conflicts with current state")
        try:
            record = await self._transitions.transition(
                record.id,
                record.tenant_id,
                record.proposal_fingerprint,
                ActionState.REJECTED,
                trusted_context.principal_id,
                ActionEventType.CUSTOMER_REJECTED,
                None,
            )
        except (
            ActionExpiredError,
            ConcurrentActionUpdateError,
            InvalidActionTransitionError,
            ProposalFingerprintMismatchError,
        ):
            current = await self._get_scoped(action_request_id, trusted_context)
            if _same_customer_decision(current, "rejected", proposal_fingerprint):
                return self.view(current)
            raise ActionDecisionConflictError(
                "action decision conflicts with current state"
            ) from None
        return self.view(record)

    @staticmethod
    def view(record: ActionRequestRecord, *, currency_code: str | None = None) -> ActionRequestView:
        """Project only safe owner-visible fields from the durable action record."""

        proposal = parse_action_proposal_payload(record.proposal_payload)
        if proposal.action_type is not record.action_type:
            raise TypeError("stored action type and proposal payload disagree")
        if isinstance(proposal, CancelOrderProposal):
            summary = f"Cancel order {proposal.order_id}"
        elif isinstance(proposal, RescheduleDeliveryProposal):
            summary = (
                f"Reschedule order {proposal.order_id} to delivery slot {proposal.delivery_slot_id}"
            )
        elif isinstance(proposal, ReturnProposal):
            summary = (
                f"Request a return for order {proposal.order_id} ({len(proposal.items)} items)"
            )
        elif isinstance(proposal, SupportTicketProposal):
            summary = f"Contact support: {proposal.subject}"
        elif isinstance(proposal, RefundProposal):
            if currency_code is None:
                summary = (
                    f"Refund request for order {proposal.order_id}; currency is unavailable. "
                    "This does not mean payment was sent."
                )
            else:
                summary = (
                    f"Request a refund of {proposal.amount:.2f} {currency_code} "
                    f"for order {proposal.order_id}; this creates a request, not a payment."
                )
        else:
            raise TypeError("stored action type and proposal payload disagree")

        state = ActionState(record.state)
        required_next_actor: Literal["customer", "support_supervisor", "none"]
        if state is ActionState.AWAITING_CONFIRMATION:
            required_next_actor = "customer"
        elif state is ActionState.AWAITING_APPROVAL:
            required_next_actor = "support_supervisor"
        else:
            required_next_actor = "none"
        customer_decision = record.customer_confirmation_decision
        if customer_decision not in {None, "confirmed", "rejected"}:
            raise ValueError("stored customer decision is outside the bounded allowlist")
        result_status = record.verification_status
        if result_status not in {None, "verified", "mismatched", "unavailable"}:
            raise ValueError("stored verification status is outside the bounded allowlist")
        return ActionRequestView(
            action_request_id=record.id,
            action_type=record.action_type,
            state=state,
            proposal_fingerprint=record.proposal_fingerprint,
            proposal=proposal,
            safe_summary=summary[:500],
            currency_code=currency_code,
            required_next_actor=required_next_actor,
            expires_at=record.expires_at,
            customer_decision=cast(Literal["confirmed", "rejected"] | None, customer_decision),
            result_status=cast(
                Literal["verified", "mismatched", "unavailable"] | None, result_status
            ),
        )

    async def _get_scoped(
        self, action_request_id: UUID, trusted_context: TrustedContext
    ) -> ActionRequestRecord:
        customer_id = trusted_context.customer_id
        if customer_id is None:
            raise ActionDecisionForbiddenError("customer action authority is required")
        return await self._transitions.get_scoped(
            action_request_id, trusted_context.tenant_id, customer_id
        )

    @staticmethod
    def _require_customer_context(trusted_context: TrustedContext) -> None:
        if not has_customer_authority(trusted_context):
            raise ActionDecisionForbiddenError("customer action authority is required")

    @staticmethod
    def _require_fingerprint(record: ActionRequestRecord, fingerprint: str) -> None:
        if fingerprint != record.proposal_fingerprint:
            raise ActionDecisionConflictError("action decision conflicts with current state")

    async def _expire_stale(
        self, record: ActionRequestRecord, trusted_context: TrustedContext
    ) -> ActionRequestRecord:
        try:
            return await self._transitions.transition(
                record.id,
                record.tenant_id,
                record.proposal_fingerprint,
                ActionState.EXPIRED,
                None,
                ActionEventType.EXPIRED,
                "stale",
            )
        except ActionExpiredError as error:
            if error.record is not None:
                return error.record
            return await self._get_scoped(record.id, trusted_context)
        except (
            ConcurrentActionUpdateError,
            InvalidActionTransitionError,
            ProposalFingerprintMismatchError,
        ):
            # A customer decision may have won the lock while the fresh Commerce
            # reads ran. Its durable result will be observed by the caller's retry.
            return await self._get_scoped(record.id, trusted_context)


def _same_customer_decision(
    record: ActionRequestRecord, decision: Literal["confirmed", "rejected"], fingerprint: str
) -> bool:
    return (
        record.customer_confirmation_decision == decision
        and record.customer_confirmation_fingerprint == fingerprint
        and record.proposal_fingerprint == fingerprint
    )


def _decision_gates_satisfied(record: ActionRequestRecord) -> bool:
    if (
        record.policy_allowed is not True
        or record.confirmation_required is not True
        or record.customer_confirmation_decision != "confirmed"
        or record.customer_confirmation_fingerprint != record.proposal_fingerprint
    ):
        return False
    if record.approval_required:
        return (
            record.supervisor_approval_decision == "approved"
            and record.supervisor_approval_fingerprint == record.proposal_fingerprint
        )
    return True
