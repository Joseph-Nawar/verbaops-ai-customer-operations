"""Customer-scoped recovery for ambiguous, already-dispatched action writes."""

from __future__ import annotations

from typing import Any
from uuid import UUID

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
from verbaops.actions.transitions import (
    ActionEventType,
    ActionRequestRecord,
    ActionTransitionService,
)
from verbaops.actions.verification import (
    OrderShipmentReadBack,
    VerificationResult,
    VerificationStatus,
    verify_postcondition,
)
from verbaops.auth.context import Role, TrustedContext
from verbaops.commerce.client import CommerceClient, CommerceWriteResult
from verbaops.commerce.errors import (
    CommerceError,
    CommerceWriteAmbiguousError,
    CommerceWritePreDispatchError,
    CommerceWriteRejected,
)
from verbaops.commerce.models import (
    RefundCreateRequest,
    ReturnCreateItemRequest,
    ReturnCreateRequest,
    SupportTicketCategory,
    SupportTicketCreateRequest,
)


class ActionReconciliationForbiddenError(PermissionError):
    """The supplied trusted identity is not the owning customer."""


class ActionReconciler:
    """Read back or replay one unresolved action without changing its logical write."""

    def __init__(
        self,
        *,
        commerce_client: CommerceClient,
        transition_service: ActionTransitionService,
    ) -> None:
        self._commerce = commerce_client
        self._transitions = transition_service

    async def reconcile(
        self, action_request_id: UUID, trusted_context: TrustedContext
    ) -> ActionRequestRecord:
        """Recover an expired execution lease, then read or replay an unresolved action."""

        if (
            trusted_context.roles != frozenset({Role.CUSTOMER})
            or trusted_context.customer_id is None
        ):
            raise ActionReconciliationForbiddenError("customer action authority is required")
        record = await self._transitions.get_scoped(
            action_request_id, trusted_context.tenant_id, trusted_context.customer_id
        )
        if record.state is ActionState.EXECUTING:
            record = await self._transitions.recover_expired_execution(
                record.id,
                record.tenant_id,
                record.customer_id,
                record.proposal_fingerprint,
            )
        if record.state is not ActionState.UNRESOLVED:
            return record
        proposal = _parse_proposal(record)
        claim = await self._transitions.claim_reconciliation(
            record.id,
            record.tenant_id,
            record.customer_id,
            record.proposal_fingerprint,
        )
        if not claim.claimed or claim.lease_owner is None:
            return claim.record
        record = claim.record
        lease_owner = claim.lease_owner

        readback: object | None = None
        verification = VerificationResult(
            VerificationStatus.UNAVAILABLE, None, "read_back_unavailable"
        )
        # Known target resources, plus cancel/reschedule targets derivable from the
        # immutable proposal, must be read before the same-key write is considered.
        if _can_read_before_replay(record, proposal):
            try:
                readback = await self._read_back(record, proposal)
                verification = verify_postcondition(record, None, readback)
            except CommerceError:
                verification = VerificationResult(
                    VerificationStatus.UNAVAILABLE, None, "read_back_unavailable"
                )
            if verification.status is VerificationStatus.VERIFIED:
                return await self._finish(
                    record,
                    trusted_context,
                    lease_owner,
                    target_state=ActionState.SUCCEEDED,
                    event_type=ActionEventType.VERIFICATION_SUCCEEDED,
                    reason_code="verified",
                    status_code=record.commerce_status_code,
                    error_code=None,
                    resource_id=verification.verified_resource_id,
                    verified_resource_id=verification.verified_resource_id,
                    verification_status=verification.status.value,
                )
            # A created resource with a known ID but contradictory fields is not
            # replayed: preserve the evidence as unresolved for human review.
            if (
                record.action_type
                in {
                    ActionType.INITIATE_RETURN,
                    ActionType.CREATE_SUPPORT_TICKET,
                    ActionType.REQUEST_REFUND,
                }
                and record.commerce_resource_id is not None
                and verification.status is VerificationStatus.MISMATCHED
            ):
                return await self._finish(
                    record,
                    trusted_context,
                    lease_owner,
                    target_state=ActionState.UNRESOLVED,
                    event_type=ActionEventType.UNRESOLVED,
                    reason_code=verification.reason_code,
                    status_code=record.commerce_status_code,
                    error_code=record.commerce_error_code,
                    resource_id=record.commerce_resource_id,
                    verification_status=verification.status.value,
                )

        try:
            result = await self._replay_with_bounded_pre_dispatch_retry(record, proposal)
        except CommerceWriteRejected as error:
            return await self._finish(
                record,
                trusted_context,
                lease_owner,
                target_state=ActionState.FAILED,
                event_type=ActionEventType.STATE_TRANSITION,
                reason_code=error.error_code or "commerce_rejected",
                status_code=error.status_code,
                error_code=error.error_code,
                resource_id=record.commerce_resource_id,
                verification_status=verification.status.value
                if _can_read_before_replay(record, proposal)
                else None,
            )
        except (CommerceWriteAmbiguousError, CommerceWritePreDispatchError) as error:
            return await self._finish(
                record,
                trusted_context,
                lease_owner,
                target_state=ActionState.UNRESOLVED,
                event_type=ActionEventType.UNRESOLVED,
                reason_code=error.error_code or "ambiguous_write_outcome",
                status_code=error.status_code,
                error_code=error.error_code,
                resource_id=record.commerce_resource_id,
                verification_status=verification.status.value
                if _can_read_before_replay(record, proposal)
                else None,
            )

        try:
            readback = await self._read_back(record, proposal, write_result=result)
            verification = verify_postcondition(record, result, readback)
        except CommerceError:
            verification = VerificationResult(
                VerificationStatus.UNAVAILABLE, None, "read_back_unavailable"
            )
        resource_id = _write_resource_id(record.action_type, result)
        if verification.status is VerificationStatus.VERIFIED:
            return await self._finish(
                record,
                trusted_context,
                lease_owner,
                target_state=ActionState.SUCCEEDED,
                event_type=ActionEventType.VERIFICATION_SUCCEEDED,
                reason_code="verified",
                status_code=result.status_code,
                error_code=None,
                resource_id=resource_id,
                verified_resource_id=verification.verified_resource_id,
                verification_status=verification.status.value,
            )
        return await self._finish(
            record,
            trusted_context,
            lease_owner,
            target_state=ActionState.UNRESOLVED,
            event_type=ActionEventType.UNRESOLVED,
            reason_code=verification.reason_code,
            status_code=result.status_code,
            error_code=None,
            resource_id=resource_id or record.commerce_resource_id,
            verification_status=verification.status.value,
        )

    async def _finish(
        self,
        record: ActionRequestRecord,
        trusted_context: TrustedContext,
        lease_owner: UUID,
        *,
        target_state: ActionState,
        event_type: ActionEventType,
        reason_code: str | None,
        status_code: int | None,
        error_code: str | None,
        resource_id: UUID | None,
        verified_resource_id: UUID | None = None,
        verification_status: str | None = None,
    ) -> ActionRequestRecord:
        customer_id = trusted_context.customer_id
        if customer_id is None:
            raise ActionReconciliationForbiddenError("customer action authority is required")
        return await self._transitions.record_reconciliation_outcome(
            record.id,
            record.tenant_id,
            customer_id,
            record.proposal_fingerprint,
            lease_owner,
            target_state=target_state,
            event_type=event_type,
            reason_code=reason_code,
            status_code=status_code,
            error_code=error_code,
            resource_id=resource_id,
            verified_resource_id=verified_resource_id,
            verification_status=verification_status,
        )

    async def _replay_with_bounded_pre_dispatch_retry(
        self, record: ActionRequestRecord, proposal: ActionProposal
    ) -> CommerceWriteResult[Any]:
        for attempt in range(2):
            try:
                return await self._dispatch(record, proposal)
            except CommerceWritePreDispatchError:
                if attempt == 1:
                    raise
        raise RuntimeError("bounded replay loop ended unexpectedly")

    async def _dispatch(
        self, record: ActionRequestRecord, proposal: ActionProposal
    ) -> CommerceWriteResult[Any]:
        if isinstance(proposal, CancelOrderProposal):
            return await self._commerce.cancel_order(
                proposal.order_id, record.customer_id, record.idempotency_key
            )
        if isinstance(proposal, RescheduleDeliveryProposal):
            return await self._commerce.reschedule_delivery(
                proposal.order_id,
                record.customer_id,
                proposal.delivery_slot_id,
                record.idempotency_key,
            )
        if isinstance(proposal, ReturnProposal):
            return_request = ReturnCreateRequest(
                order_id=proposal.order_id,
                reason=proposal.reason,
                items=[
                    ReturnCreateItemRequest(
                        order_item_id=item.order_item_id, quantity=item.quantity
                    )
                    for item in proposal.items
                ],
            )
            return await self._commerce.create_return(
                record.customer_id, return_request, record.idempotency_key
            )
        if isinstance(proposal, SupportTicketProposal):
            ticket_request = SupportTicketCreateRequest(
                order_id=proposal.order_id,
                category=SupportTicketCategory(proposal.category.value),
                subject=proposal.subject,
                description=proposal.description,
            )
            return await self._commerce.create_support_ticket(
                record.customer_id, ticket_request, record.idempotency_key
            )
        if isinstance(proposal, RefundProposal):
            refund_request = RefundCreateRequest(amount=proposal.amount, reason=proposal.reason)
            return await self._commerce.request_refund(
                proposal.order_id,
                record.customer_id,
                refund_request,
                None,
                record.idempotency_key,
            )
        raise TypeError("stored action type and proposal payload disagree")

    async def _read_back(
        self,
        record: ActionRequestRecord,
        proposal: ActionProposal,
        *,
        write_result: CommerceWriteResult[Any] | None = None,
    ) -> object:
        if isinstance(proposal, CancelOrderProposal):
            order = await self._commerce.get_order(proposal.order_id, record.customer_id)
            shipment = None
            if (
                write_result is not None
                and getattr(write_result.response, "shipment", None) is not None
            ):
                shipment = await self._commerce.get_shipment(proposal.order_id, record.customer_id)
            elif write_result is None:
                try:
                    shipment = await self._commerce.get_shipment(
                        proposal.order_id, record.customer_id
                    )
                except CommerceError:
                    # Order status is authoritative for cancellation; an absent shipment
                    # cannot manufacture a successful state transition.
                    shipment = None
            return OrderShipmentReadBack(order=order, shipment=shipment)
        if isinstance(proposal, RescheduleDeliveryProposal):
            return await self._commerce.get_shipment(proposal.order_id, record.customer_id)
        if isinstance(proposal, ReturnProposal):
            resource_id = (
                getattr(write_result.response, "id", None)
                if write_result is not None
                else record.commerce_resource_id
            )
            if resource_id is None:
                raise CommerceWriteAmbiguousError(status_code=None, error_code=None)
            return await self._commerce.get_return(resource_id, record.customer_id)
        if isinstance(proposal, SupportTicketProposal):
            resource_id = (
                getattr(write_result.response, "id", None)
                if write_result is not None
                else record.commerce_resource_id
            )
            if resource_id is None:
                raise CommerceWriteAmbiguousError(status_code=None, error_code=None)
            return await self._commerce.get_support_ticket(resource_id, record.customer_id)
        if isinstance(proposal, RefundProposal):
            return await self._commerce.get_refunds(proposal.order_id, record.customer_id)
        raise TypeError("stored action type and proposal payload disagree")


def _parse_proposal(record: ActionRequestRecord) -> ActionProposal:
    proposal = parse_action_proposal_payload(record.proposal_payload)
    if proposal.action_type is not record.action_type:
        raise TypeError("stored action type and proposal payload disagree")
    if tuple(proposal_target_ids(proposal)) != record.target_ids:
        raise TypeError("stored action targets and proposal payload disagree")
    return proposal


def _can_read_before_replay(record: ActionRequestRecord, proposal: ActionProposal) -> bool:
    if isinstance(proposal, (CancelOrderProposal, RescheduleDeliveryProposal)):
        return True
    return record.commerce_resource_id is not None


def _write_resource_id(action_type: ActionType, result: CommerceWriteResult[Any]) -> UUID | None:
    response = result.response
    if action_type is ActionType.CANCEL_ORDER:
        return getattr(getattr(response, "order", None), "id", None)
    return getattr(response, "id", None)
