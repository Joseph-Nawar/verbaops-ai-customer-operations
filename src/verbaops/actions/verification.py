"""Exact customer-scoped postcondition checks for the five Stage 6 actions."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from verbaops.actions.models import (
    ActionType,
    CancelOrderProposal,
    RefundProposal,
    RescheduleDeliveryProposal,
    ReturnProposal,
    SupportTicketProposal,
    parse_action_proposal_payload,
)
from verbaops.actions.transitions import ActionRequestRecord
from verbaops.commerce.client import CommerceWriteResult
from verbaops.commerce.models import (
    CancelOrderResponse,
    OrderResponse,
    RefundResponse,
    RefundStatus,
    ReturnResponse,
    ReturnStatus,
    ShipmentResponse,
    SupportTicketResponse,
    SupportTicketStatus,
    WriteRefundResponse,
)


class VerificationStatus(StrEnum):
    """Bounded exact read-back outcome values persisted on an action request."""

    VERIFIED = "verified"
    MISMATCHED = "mismatched"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class OrderShipmentReadBack:
    """Customer-scoped cancellation read-back pair."""

    order: OrderResponse | None
    shipment: ShipmentResponse | None


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Secret-safe verifier outcome and exact resource evidence, when verified."""

    status: VerificationStatus
    verified_resource_id: UUID | None
    reason_code: str


def verify_postcondition(
    action: ActionRequestRecord,
    write_result: CommerceWriteResult[Any] | None,
    read_back: object | None,
) -> VerificationResult:
    """Require exact identifiers, trusted scope, requested values, and initial status."""

    proposal = parse_action_proposal_payload(action.proposal_payload)
    if proposal.action_type is not action.action_type:
        return _mismatched()
    if action.action_type is ActionType.CANCEL_ORDER and isinstance(proposal, CancelOrderProposal):
        return _verify_cancel(action, proposal, write_result, read_back)
    if action.action_type is ActionType.RESCHEDULE_DELIVERY and isinstance(
        proposal, RescheduleDeliveryProposal
    ):
        return _verify_reschedule(action, proposal, write_result, read_back)
    if action.action_type is ActionType.INITIATE_RETURN and isinstance(proposal, ReturnProposal):
        return _verify_return(action, proposal, write_result, read_back)
    if action.action_type is ActionType.CREATE_SUPPORT_TICKET and isinstance(
        proposal, SupportTicketProposal
    ):
        return _verify_ticket(action, proposal, write_result, read_back)
    if action.action_type is ActionType.REQUEST_REFUND and isinstance(proposal, RefundProposal):
        return _verify_refund(action, proposal, write_result, read_back)
    return _mismatched()


def _verify_cancel(
    action: ActionRequestRecord,
    proposal: CancelOrderProposal,
    write_result: CommerceWriteResult[Any] | None,
    read_back: object | None,
) -> VerificationResult:
    if not isinstance(read_back, OrderShipmentReadBack) or read_back.order is None:
        return _unavailable()
    order = read_back.order
    if (
        order.id != proposal.order_id
        or order.customer_id != action.customer_id
        or order.status.value != "cancelled"
    ):
        return _mismatched()
    if write_result is not None:
        response = write_result.response
        if (
            not isinstance(response, CancelOrderResponse)
            or response.order.id != proposal.order_id
            or response.order.customer_id != action.customer_id
            or response.order.status.value != "cancelled"
        ):
            return _mismatched()
        if response.shipment is not None and (
            read_back.shipment is None
            or read_back.shipment.id != response.shipment.id
            or read_back.shipment.order_id != proposal.order_id
            or read_back.shipment.status.value != "cancelled"
            or response.shipment.status.value != "cancelled"
        ):
            return _mismatched()
    if read_back.shipment is not None and (
        read_back.shipment.order_id != proposal.order_id
        or read_back.shipment.status.value != "cancelled"
    ):
        return _mismatched()
    return _verified(proposal.order_id)


def _verify_reschedule(
    action: ActionRequestRecord,
    proposal: RescheduleDeliveryProposal,
    write_result: CommerceWriteResult[Any] | None,
    read_back: object | None,
) -> VerificationResult:
    if not isinstance(read_back, ShipmentResponse):
        return _unavailable()
    expected_shipment_id = action.commerce_resource_id
    if write_result is not None:
        response = write_result.response
        if (
            not isinstance(response, ShipmentResponse)
            or response.order_id != proposal.order_id
            or response.delivery_slot_id != proposal.delivery_slot_id
        ):
            return _mismatched()
        expected_shipment_id = response.id
    if (
        read_back.order_id != proposal.order_id
        or read_back.delivery_slot_id != proposal.delivery_slot_id
        or (expected_shipment_id is not None and read_back.id != expected_shipment_id)
    ):
        return _mismatched()
    return _verified(read_back.id)


def _verify_return(
    action: ActionRequestRecord,
    proposal: ReturnProposal,
    write_result: CommerceWriteResult[Any] | None,
    read_back: object | None,
) -> VerificationResult:
    if not isinstance(read_back, ReturnResponse):
        return _unavailable()
    expected_resource_id = action.commerce_resource_id
    expected_items = {item.order_item_id: item.quantity for item in proposal.items}
    if write_result is not None:
        response = write_result.response
        if not isinstance(response, ReturnResponse):
            return _mismatched()
        response_items = {item.order_item_id: item.quantity for item in response.items}
        if (
            response.order_id != proposal.order_id
            or response.reason != proposal.reason
            or response.status is not ReturnStatus.REQUESTED
            or len(response.items) != len(expected_items)
            or response_items != expected_items
        ):
            return _mismatched()
        expected_resource_id = response.id
    observed_items = {item.order_item_id: item.quantity for item in read_back.items}
    if (
        (expected_resource_id is not None and read_back.id != expected_resource_id)
        or read_back.order_id != proposal.order_id
        or read_back.reason != proposal.reason
        or read_back.status is not ReturnStatus.REQUESTED
        or len(read_back.items) != len(expected_items)
        or observed_items != expected_items
    ):
        return _mismatched()
    return _verified(read_back.id)


def _verify_ticket(
    action: ActionRequestRecord,
    proposal: SupportTicketProposal,
    write_result: CommerceWriteResult[Any] | None,
    read_back: object | None,
) -> VerificationResult:
    if not isinstance(read_back, SupportTicketResponse):
        return _unavailable()
    expected_resource_id = action.commerce_resource_id
    if write_result is not None:
        response = write_result.response
        if not isinstance(response, SupportTicketResponse):
            return _mismatched()
        if (
            response.customer_id != action.customer_id
            or response.order_id != proposal.order_id
            or response.category.value != proposal.category.value
            or response.subject != proposal.subject
            or response.description != proposal.description
            or response.status is not SupportTicketStatus.OPEN
        ):
            return _mismatched()
        expected_resource_id = response.id
    if (
        (expected_resource_id is not None and read_back.id != expected_resource_id)
        or read_back.customer_id != action.customer_id
        or read_back.order_id != proposal.order_id
        or read_back.category.value != proposal.category.value
        or read_back.subject != proposal.subject
        or read_back.description != proposal.description
        or read_back.status is not SupportTicketStatus.OPEN
    ):
        return _mismatched()
    return _verified(read_back.id)


def _verify_refund(
    action: ActionRequestRecord,
    proposal: RefundProposal,
    write_result: CommerceWriteResult[Any] | None,
    read_back: object | None,
) -> VerificationResult:
    if not isinstance(read_back, list) or not all(
        isinstance(refund, RefundResponse) for refund in read_back
    ):
        return _unavailable()
    expected_resource_id = action.commerce_resource_id
    if write_result is not None:
        response = write_result.response
        if not isinstance(response, WriteRefundResponse):
            return _mismatched()
        expected_resource_id = response.id
        if (
            response.amount != proposal.amount
            or response.reason != proposal.reason
            or response.status is not RefundStatus.APPROVED
            or response.requires_manual_approval is not action.approval_required
        ):
            return _mismatched()
    if expected_resource_id is None:
        return _unavailable()
    refund = next((item for item in read_back if item.id == expected_resource_id), None)
    if refund is None:
        return _unavailable()
    if (
        refund.amount != format(proposal.amount, ".2f")
        or refund.reason != proposal.reason
        or refund.status is not RefundStatus.APPROVED
        or refund.requires_manual_approval is not action.approval_required
    ):
        return _mismatched()
    return _verified(refund.id)


def _verified(resource_id: UUID) -> VerificationResult:
    return VerificationResult(VerificationStatus.VERIFIED, resource_id, "verified")


def _mismatched() -> VerificationResult:
    return VerificationResult(VerificationStatus.MISMATCHED, None, "postcondition_mismatch")


def _unavailable() -> VerificationResult:
    return VerificationResult(VerificationStatus.UNAVAILABLE, None, "read_back_unavailable")
