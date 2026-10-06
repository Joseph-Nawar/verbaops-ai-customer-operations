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
from verbaops.actions.proposals import ActionFreshnessResult, ActionProposalService
from verbaops.actions.transitions import (
    ActionEventType,
    ActionExpiredError,
    ActionRequestNotFoundError,
    ActionRequestRecord,
    ActionTransitionService,
    ConcurrentActionUpdateError,
    InvalidActionTransitionError,
    ProposalFingerprintMismatchError,
)
from verbaops.auth.context import (
    TrustedContext,
    has_customer_authority,
    has_supervisor_authority,
)
from verbaops.commerce.client import CommerceClient
from verbaops.commerce.errors import CommerceError


class ActionDecisionConflictError(RuntimeError):
    """The requested decision does not match the current durable action state."""


class ActionDecisionForbiddenError(PermissionError):
    """Only the owning customer principal may decide a customer action."""


class ActionSupervisorForbiddenError(ActionDecisionForbiddenError):
    """Only a different trusted supervisor principal may decide an approval gate."""


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
    confirmation_required: bool = False
    approval_required: bool = False
    policy_reason_code: (
        Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")] | None
    ) = None
    permitted_operations: tuple[
        Literal["confirm", "reject", "approve", "approval_reject", "reconcile"], ...
    ] = ()


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

        record = await self._get_view_scoped(action_request_id, trusted_context)
        currency_code: str | None = None
        if (
            record.action_type is ActionType.REQUEST_REFUND
            and ActionState(record.state)
            in {
                ActionState.AWAITING_CONFIRMATION,
                ActionState.AWAITING_APPROVAL,
            }
            and record.tenant_id == self._commerce.tenant_id
        ):
            try:
                currency = await self._commerce.get_tenant_currency()
            except CommerceError:
                currency = None
            currency_code = currency.currency_code if currency is not None else None
        return self.view_for_context(record, trusted_context, currency_code=currency_code)

    @staticmethod
    def view_for_context(
        record: ActionRequestRecord,
        trusted_context: TrustedContext,
        *,
        currency_code: str | None = None,
    ) -> ActionRequestView:
        """Project durable state plus server-derived actor operations."""

        if record.tenant_id != trusted_context.tenant_id:
            raise ActionDecisionForbiddenError("action request not found")
        customer_scope = has_customer_authority(trusted_context) and (
            trusted_context.customer_id == record.customer_id
        )
        supervisor_scope = has_supervisor_authority(trusted_context) and record.approval_required
        if not customer_scope and not supervisor_scope:
            raise ActionDecisionForbiddenError("action request not found")
        return ActionDecisionService.view(
            record,
            currency_code=currency_code,
            permitted_operations=_permitted_operations(record, trusted_context),
        )

    async def approve(
        self,
        action_request_id: UUID,
        trusted_context: TrustedContext,
        proposal_fingerprint: str,
    ) -> ActionRequestView:
        """Approve a current supervisor-gated action before customer confirmation."""

        return await self._supervisor_decision(
            action_request_id,
            trusted_context,
            proposal_fingerprint,
            decision="approved",
        )

    async def reject_approval(
        self,
        action_request_id: UUID,
        trusted_context: TrustedContext,
        proposal_fingerprint: str,
    ) -> ActionRequestView:
        """Reject a current supervisor-gated action without running Commerce writes."""

        return await self._supervisor_decision(
            action_request_id,
            trusted_context,
            proposal_fingerprint,
            decision="rejected",
        )

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
                    or record.supervisor_approval_actor_id is None
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
    def view(
        record: ActionRequestRecord,
        *,
        currency_code: str | None = None,
        permitted_operations: tuple[
            Literal["confirm", "reject", "approve", "approval_reject", "reconcile"], ...
        ] = (),
    ) -> ActionRequestView:
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
            confirmation_required=record.confirmation_required,
            approval_required=record.approval_required,
            policy_reason_code=record.policy_reason_code,
            permitted_operations=permitted_operations,
        )

    async def _supervisor_decision(
        self,
        action_request_id: UUID,
        trusted_context: TrustedContext,
        proposal_fingerprint: str,
        *,
        decision: Literal["approved", "rejected"],
    ) -> ActionRequestView:
        _require_supervisor_context(trusted_context)
        record = await self._get_supervisor_scoped(action_request_id, trusted_context)
        if not record.approval_required:
            raise ActionRequestNotFoundError("action request not found in approval scope")
        self._require_fingerprint(record, proposal_fingerprint)
        if record.proposing_principal_id == trusted_context.principal_id:
            raise ActionSupervisorForbiddenError("the proposing principal cannot decide its action")
        if record.supervisor_approval_decision is not None:
            if _same_supervisor_decision(record, decision, proposal_fingerprint):
                return self.view(record)
            raise ActionDecisionConflictError("action decision conflicts with current state")
        if ActionState(record.state) is not ActionState.AWAITING_APPROVAL:
            raise ActionDecisionConflictError("action decision conflicts with current state")

        try:
            freshness = await self._freshness.refresh(record)
        except CommerceError:
            raise ActionFreshnessUnavailableError("current action facts are unavailable") from None
        currency_code = (
            freshness.canonical_currency
            if record.action_type is ActionType.REQUEST_REFUND
            else None
        )
        if not _supervisor_freshness_matches(record, freshness):
            current = await self._expire_stale(record, trusted_context, supervisor_scope=True)
            if _same_supervisor_decision(current, decision, proposal_fingerprint):
                return self.view(current, currency_code=currency_code)
            raise ActionDecisionConflictError("action decision conflicts with current state")

        target_state = (
            ActionState.AWAITING_CONFIRMATION if decision == "approved" else ActionState.REJECTED
        )
        event_type = (
            ActionEventType.SUPERVISOR_APPROVED
            if decision == "approved"
            else ActionEventType.SUPERVISOR_REJECTED
        )
        try:
            record = await self._transitions.transition(
                record.id,
                record.tenant_id,
                record.proposal_fingerprint,
                target_state,
                trusted_context.principal_id,
                event_type,
                "supervisor_approved" if decision == "approved" else "supervisor_rejected",
            )
        except (
            ActionExpiredError,
            ConcurrentActionUpdateError,
            InvalidActionTransitionError,
            ProposalFingerprintMismatchError,
        ):
            current = await self._get_supervisor_scoped(action_request_id, trusted_context)
            if _same_supervisor_decision(current, decision, proposal_fingerprint):
                return self.view(current, currency_code=currency_code)
            raise ActionDecisionConflictError(
                "action decision conflicts with current state"
            ) from None
        return self.view(record, currency_code=currency_code)

    async def _get_scoped(
        self, action_request_id: UUID, trusted_context: TrustedContext
    ) -> ActionRequestRecord:
        customer_id = trusted_context.customer_id
        if customer_id is None:
            raise ActionDecisionForbiddenError("customer action authority is required")
        return await self._transitions.get_scoped(
            action_request_id, trusted_context.tenant_id, customer_id
        )

    async def _get_supervisor_scoped(
        self, action_request_id: UUID, trusted_context: TrustedContext
    ) -> ActionRequestRecord:
        return await self._transitions.get_tenant_scoped(
            action_request_id, trusted_context.tenant_id
        )

    async def _get_view_scoped(
        self, action_request_id: UUID, trusted_context: TrustedContext
    ) -> ActionRequestRecord:
        if has_supervisor_authority(trusted_context):
            try:
                record = await self._get_supervisor_scoped(action_request_id, trusted_context)
            except ActionRequestNotFoundError:
                if has_customer_authority(trusted_context):
                    return await self._get_scoped(action_request_id, trusted_context)
                raise
            if record.approval_required:
                return record
            if has_customer_authority(trusted_context):
                return await self._get_scoped(action_request_id, trusted_context)
            raise ActionRequestNotFoundError("action request not found in approval scope")
        self._require_customer_context(trusted_context)
        return await self._get_scoped(action_request_id, trusted_context)

    @staticmethod
    def _require_customer_context(trusted_context: TrustedContext) -> None:
        if not has_customer_authority(trusted_context):
            raise ActionDecisionForbiddenError("customer action authority is required")

    @staticmethod
    def _require_fingerprint(record: ActionRequestRecord, fingerprint: str) -> None:
        if fingerprint != record.proposal_fingerprint:
            raise ActionDecisionConflictError("action decision conflicts with current state")

    async def _expire_stale(
        self,
        record: ActionRequestRecord,
        trusted_context: TrustedContext,
        *,
        supervisor_scope: bool = False,
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
            return await self._reload_after_decision(record.id, trusted_context, supervisor_scope)
        except (
            ConcurrentActionUpdateError,
            InvalidActionTransitionError,
            ProposalFingerprintMismatchError,
        ):
            # A customer decision may have won the lock while the fresh Commerce
            # reads ran. Its durable result will be observed by the caller's retry.
            return await self._reload_after_decision(record.id, trusted_context, supervisor_scope)

    async def _reload_after_decision(
        self, action_request_id: UUID, trusted_context: TrustedContext, supervisor_scope: bool
    ) -> ActionRequestRecord:
        if supervisor_scope:
            return await self._get_supervisor_scoped(action_request_id, trusted_context)
        return await self._get_scoped(action_request_id, trusted_context)


def _same_customer_decision(
    record: ActionRequestRecord, decision: Literal["confirmed", "rejected"], fingerprint: str
) -> bool:
    return (
        record.customer_confirmation_decision == decision
        and record.customer_confirmation_fingerprint == fingerprint
        and record.proposal_fingerprint == fingerprint
    )


def _same_supervisor_decision(
    record: ActionRequestRecord,
    decision: Literal["approved", "rejected"],
    fingerprint: str,
) -> bool:
    return (
        record.supervisor_approval_decision == decision
        and record.supervisor_approval_actor_id is not None
        and record.supervisor_approval_fingerprint == fingerprint
        and record.proposal_fingerprint == fingerprint
    )


def _permitted_operations(
    record: ActionRequestRecord, trusted_context: TrustedContext
) -> tuple[Literal["confirm", "reject", "approve", "approval_reject", "reconcile"], ...]:
    """Describe bounded presentation capabilities without replacing POST authorization."""

    operations: list[Literal["confirm", "reject", "approve", "approval_reject", "reconcile"]] = []
    state = ActionState(record.state)
    owns_action = has_customer_authority(trusted_context) and (
        trusted_context.customer_id == record.customer_id
    )
    if owns_action:
        if state is ActionState.AWAITING_CONFIRMATION and record.confirmation_required:
            operations.extend(("confirm", "reject"))
        elif state is ActionState.AWAITING_APPROVAL:
            operations.append("reject")
        elif state is ActionState.UNRESOLVED:
            operations.append("reconcile")

    if has_supervisor_authority(trusted_context) and record.approval_required:
        if state is ActionState.AWAITING_APPROVAL and (
            record.proposing_principal_id != trusted_context.principal_id
        ):
            operations.extend(("approve", "approval_reject"))
        elif state is ActionState.UNRESOLVED:
            operations.append("reconcile")
    return tuple(dict.fromkeys(operations))


def _supervisor_freshness_matches(
    record: ActionRequestRecord, freshness: ActionFreshnessResult
) -> bool:
    current_fingerprint = freshness.proposal_fingerprint
    decision = freshness.policy_decision
    currency = freshness.canonical_currency
    return (
        current_fingerprint == record.proposal_fingerprint
        and decision.allowed
        and decision.confirmation_required
        and decision.approval_required
        and (record.action_type is not ActionType.REQUEST_REFUND or currency is not None)
    )


def _require_supervisor_context(trusted_context: TrustedContext) -> None:
    if not has_supervisor_authority(trusted_context):
        raise ActionSupervisorForbiddenError("supervisor action authority is required")


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
            and record.supervisor_approval_actor_id is not None
            and record.supervisor_approval_fingerprint == record.proposal_fingerprint
        )
    return True
