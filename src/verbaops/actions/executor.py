"""Internal, fixed-route Commerce execution for customer-confirmed actions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import ValidationError

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
    proposal_target_ids,
)
from verbaops.actions.policy import PolicyDecision
from verbaops.actions.proposals import ActionProposalService
from verbaops.actions.transitions import (
    ActionEventType,
    ActionRequestRecord,
    ActionTransitionService,
)
from verbaops.commerce.client import CommerceClient, CommerceWriteResult
from verbaops.commerce.errors import (
    CommerceWriteAmbiguousError,
    CommerceWritePreDispatchError,
    CommerceWriteRejected,
)
from verbaops.commerce.models import (
    CancelOrderResponse,
    RefundCreateRequest,
    RefundStatus,
    ReturnCreateItemRequest,
    ReturnCreateRequest,
    ReturnResponse,
    ReturnStatus,
    ShipmentResponse,
    SupportTicketCategory,
    SupportTicketCreateRequest,
    SupportTicketResponse,
    SupportTicketStatus,
    WriteRefundResponse,
)

DispatchCallable = Callable[
    [ActionRequestRecord, ActionProposal], Awaitable[CommerceWriteResult[Any]]
]


class ActionExecutor:
    """Claim and execute one already-confirmed action through fixed server routes."""

    def __init__(
        self,
        *,
        commerce_client: CommerceClient,
        transition_service: ActionTransitionService,
        freshness_service: ActionProposalService,
    ) -> None:
        self._commerce = commerce_client
        self._transitions = transition_service
        self._freshness = freshness_service
        self._dispatchers: dict[ActionType, DispatchCallable] = {
            ActionType.CANCEL_ORDER: self._cancel,
            ActionType.RESCHEDULE_DELIVERY: self._reschedule,
            ActionType.INITIATE_RETURN: self._return,
            ActionType.CREATE_SUPPORT_TICKET: self._ticket,
            ActionType.REQUEST_REFUND: self._refund,
        }

    async def execute_ready(self, action_request_id: UUID) -> ActionRequestRecord:
        """Refresh, claim, and dispatch one ready action; never trust caller-supplied route data."""

        record = await self._transitions.get(action_request_id)
        if record.state is not ActionState.READY_TO_EXECUTE:
            return record
        if not _record_gates_satisfied(record):
            return record

        proposal = _parse_proposal(record)
        freshness = await self._freshness.refresh(record)
        decision: PolicyDecision = freshness.policy_decision
        if freshness.proposal_fingerprint != record.proposal_fingerprint:
            return await self._transitions.transition(
                action_request_id=record.id,
                tenant_id=record.tenant_id,
                expected_fingerprint=record.proposal_fingerprint,
                target_state=ActionState.EXPIRED,
                actor_id=None,
                event_type=ActionEventType.EXPIRED,
                reason_code="stale",
            )
        if not decision.allowed:
            return await self._transitions.transition(
                action_request_id=record.id,
                tenant_id=record.tenant_id,
                expected_fingerprint=record.proposal_fingerprint,
                target_state=ActionState.POLICY_DENIED,
                actor_id=None,
                event_type=ActionEventType.POLICY_DENIED,
                reason_code=decision.reason_code,
                policy_decision=decision,
            )
        if (
            not decision.confirmation_required
            or decision.approval_required != record.approval_required
        ):
            return await self._transitions.transition(
                action_request_id=record.id,
                tenant_id=record.tenant_id,
                expected_fingerprint=record.proposal_fingerprint,
                target_state=ActionState.EXPIRED,
                actor_id=None,
                event_type=ActionEventType.EXPIRED,
                reason_code="stale",
            )

        claim = await self._transitions.claim_execution(
            record.id,
            record.tenant_id,
            record.proposal_fingerprint,
        )
        if not claim.claimed or claim.lease_owner is None:
            return claim.record

        result = await self._dispatch_with_bounded_pre_dispatch_retry(
            claim.record,
            proposal,
            claim.lease_owner,
        )
        return result

    async def _dispatch_with_bounded_pre_dispatch_retry(
        self,
        record: ActionRequestRecord,
        proposal: ActionProposal,
        lease_owner: UUID,
    ) -> ActionRequestRecord:
        dispatcher = self._dispatchers[record.action_type]
        for attempt in range(2):
            try:
                result = await dispatcher(record, proposal)
            except ValidationError:
                return await self._record_outcome(
                    record,
                    lease_owner,
                    target_state=ActionState.FAILED,
                    event_type=ActionEventType.STATE_TRANSITION,
                    reason_code="request_validation_rejected",
                    status_code=None,
                    error_code=None,
                    resource_id=None,
                )
            except CommerceWritePreDispatchError as error:
                if attempt == 0:
                    continue
                return await self._record_outcome(
                    record,
                    lease_owner,
                    target_state=ActionState.READY_TO_EXECUTE,
                    event_type=ActionEventType.STATE_TRANSITION,
                    reason_code="proven_non_dispatch",
                    status_code=error.status_code,
                    error_code=error.error_code,
                    resource_id=None,
                )
            except CommerceWriteRejected as error:
                return await self._record_outcome(
                    record,
                    lease_owner,
                    target_state=ActionState.FAILED,
                    event_type=ActionEventType.COMMERCE_RESPONSE,
                    reason_code=error.error_code or "commerce_rejected",
                    status_code=error.status_code,
                    error_code=error.error_code,
                    resource_id=None,
                )
            except CommerceWriteAmbiguousError as error:
                return await self._record_outcome(
                    record,
                    lease_owner,
                    target_state=ActionState.UNRESOLVED,
                    event_type=ActionEventType.UNRESOLVED,
                    reason_code=error.error_code or "ambiguous_write_outcome",
                    status_code=error.status_code,
                    error_code=error.error_code,
                    resource_id=None,
                )

            if not _response_matches_proposal(record, proposal, result.response):
                return await self._record_outcome(
                    record,
                    lease_owner,
                    target_state=ActionState.UNRESOLVED,
                    event_type=ActionEventType.UNRESOLVED,
                    reason_code="contradictory_write_response",
                    status_code=result.status_code,
                    error_code=None,
                    resource_id=None,
                )
            resource_id = _result_resource_id(record.action_type, result.response)
            return await self._record_outcome(
                record,
                lease_owner,
                target_state=ActionState.UNRESOLVED,
                event_type=ActionEventType.UNRESOLVED,
                reason_code="verification_required",
                status_code=result.status_code,
                error_code=None,
                resource_id=resource_id,
            )
        raise RuntimeError("bounded write attempt loop ended unexpectedly")

    async def _record_outcome(
        self,
        record: ActionRequestRecord,
        lease_owner: UUID,
        *,
        target_state: ActionState,
        event_type: ActionEventType,
        reason_code: str,
        status_code: int | None,
        error_code: str | None,
        resource_id: UUID | None,
    ) -> ActionRequestRecord:
        return await self._transitions.record_execution_outcome(
            record.id,
            record.tenant_id,
            record.proposal_fingerprint,
            lease_owner,
            target_state=target_state,
            event_type=event_type,
            reason_code=reason_code,
            status_code=status_code,
            error_code=error_code,
            resource_id=resource_id,
        )

    async def _cancel(
        self, record: ActionRequestRecord, proposal: ActionProposal
    ) -> CommerceWriteResult[Any]:
        if not isinstance(proposal, CancelOrderProposal):
            raise TypeError("stored action type and proposal payload disagree")
        return await self._commerce.cancel_order(
            proposal.order_id,
            record.customer_id,
            record.idempotency_key,
        )

    async def _reschedule(
        self, record: ActionRequestRecord, proposal: ActionProposal
    ) -> CommerceWriteResult[Any]:
        if not isinstance(proposal, RescheduleDeliveryProposal):
            raise TypeError("stored action type and proposal payload disagree")
        return await self._commerce.reschedule_delivery(
            proposal.order_id,
            record.customer_id,
            proposal.delivery_slot_id,
            record.idempotency_key,
        )

    async def _return(
        self, record: ActionRequestRecord, proposal: ActionProposal
    ) -> CommerceWriteResult[Any]:
        if not isinstance(proposal, ReturnProposal):
            raise TypeError("stored action type and proposal payload disagree")
        request = ReturnCreateRequest(
            order_id=proposal.order_id,
            reason=proposal.reason,
            items=[
                ReturnCreateItemRequest(order_item_id=item.order_item_id, quantity=item.quantity)
                for item in proposal.items
            ],
        )
        return await self._commerce.create_return(
            record.customer_id,
            request,
            record.idempotency_key,
        )

    async def _ticket(
        self, record: ActionRequestRecord, proposal: ActionProposal
    ) -> CommerceWriteResult[Any]:
        if not isinstance(proposal, SupportTicketProposal):
            raise TypeError("stored action type and proposal payload disagree")
        request = SupportTicketCreateRequest(
            order_id=proposal.order_id,
            category=SupportTicketCategory(proposal.category.value),
            subject=proposal.subject,
            description=proposal.description,
        )
        return await self._commerce.create_support_ticket(
            record.customer_id,
            request,
            record.idempotency_key,
        )

    async def _refund(
        self, record: ActionRequestRecord, proposal: ActionProposal
    ) -> CommerceWriteResult[Any]:
        if not isinstance(proposal, RefundProposal):
            raise TypeError("stored action type and proposal payload disagree")
        request = RefundCreateRequest(amount=proposal.amount, reason=proposal.reason)
        return await self._commerce.request_refund(
            proposal.order_id,
            record.customer_id,
            request,
            None,
            record.idempotency_key,
        )


def _parse_proposal(record: ActionRequestRecord) -> ActionProposal:
    proposal = parse_action_proposal_payload(record.proposal_payload)
    if proposal.action_type is not record.action_type:
        raise TypeError("stored action type and proposal payload disagree")
    if tuple(proposal_target_ids(proposal)) != record.target_ids:
        raise TypeError("stored action targets and proposal payload disagree")
    return proposal


def _record_gates_satisfied(record: ActionRequestRecord) -> bool:
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


def _response_matches_proposal(
    record: ActionRequestRecord,
    proposal: ActionProposal,
    response: object,
) -> bool:
    if isinstance(proposal, CancelOrderProposal):
        return (
            isinstance(response, CancelOrderResponse)
            and response.order.id == proposal.order_id
            and response.order.customer_id == record.customer_id
            and response.order.status.value == "cancelled"
            and (
                response.shipment is None
                or (
                    response.shipment.order_id == proposal.order_id
                    and response.shipment.status.value == "cancelled"
                )
            )
        )
    if isinstance(proposal, RescheduleDeliveryProposal):
        return (
            isinstance(response, ShipmentResponse)
            and isinstance(response.id, UUID)
            and response.order_id == proposal.order_id
            and response.delivery_slot_id == proposal.delivery_slot_id
        )
    if isinstance(proposal, ReturnProposal):
        if not isinstance(response, ReturnResponse):
            return False
        expected = {item.order_item_id: item.quantity for item in proposal.items}
        actual = {item.order_item_id: item.quantity for item in response.items}
        return (
            isinstance(response.id, UUID)
            and response.order_id == proposal.order_id
            and response.reason == proposal.reason
            and response.status.value == ReturnStatus.REQUESTED.value
            and actual == expected
        )
    if isinstance(proposal, SupportTicketProposal):
        if not isinstance(response, SupportTicketResponse):
            return False
        return (
            isinstance(response.id, UUID)
            and response.customer_id == record.customer_id
            and response.order_id == proposal.order_id
            and response.category.value == proposal.category.value
            and response.subject == proposal.subject
            and response.description == proposal.description
            and response.status.value == SupportTicketStatus.OPEN.value
        )
    if isinstance(proposal, RefundProposal):
        if not isinstance(response, WriteRefundResponse):
            return False
        amount = response.amount
        return (
            isinstance(response.id, UUID)
            and isinstance(amount, Decimal)
            and amount == proposal.amount
            and response.reason == proposal.reason
            and response.status is RefundStatus.APPROVED
            and response.requires_manual_approval is False
        )
    return False


def _result_resource_id(action_type: ActionType, response: object) -> UUID | None:
    if action_type is ActionType.CANCEL_ORDER:
        return getattr(getattr(response, "order", None), "id", None)
    if action_type is ActionType.RESCHEDULE_DELIVERY:
        return getattr(response, "id", None)
    return getattr(response, "id", None)
