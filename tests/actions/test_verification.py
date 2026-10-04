"""Exact customer-scoped read-back contract tests for all M6D action kinds."""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from verbaops.actions.models import (
    ActionProposal,
    CancelOrderProposal,
    RefundProposal,
    RescheduleDeliveryProposal,
    ReturnItemProposal,
    ReturnProposal,
    SupportTicketProposal,
    TicketCategory,
    proposal_target_ids,
)
from verbaops.actions.verification import (
    OrderShipmentReadBack,
    VerificationStatus,
    verify_postcondition,
)
from verbaops.commerce.client import CommerceWriteResult
from verbaops.commerce.models import (
    CancelOrderResponse,
    OrderResponse,
    OrderStatus,
    RefundResponse,
    RefundStatus,
    ReturnItemResponse,
    ReturnResponse,
    ReturnStatus,
    ShipmentResponse,
    ShipmentStatus,
    SupportTicketCategory,
    SupportTicketResponse,
    SupportTicketStatus,
    WriteRefundResponse,
)

NOW = datetime(2026, 10, 4, 12, tzinfo=UTC)


def record_for(
    proposal: ActionProposal,
    *,
    customer_id: UUID | None = None,
    resource_id: UUID | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        customer_id=customer_id or uuid4(),
        action_type=proposal.action_type,
        proposal_payload=proposal.model_dump(mode="json"),
        target_ids=proposal_target_ids(proposal),
        commerce_resource_id=resource_id,
    )


def order_response(order_id: UUID, customer_id: UUID, status: OrderStatus) -> OrderResponse:
    return OrderResponse(
        id=order_id,
        customer_id=customer_id,
        status=status,
        total="25.00",
        created_at=NOW,
        updated_at=NOW,
        items=[],
    )


def shipment_response(
    order_id: UUID,
    *,
    shipment_id: UUID | None = None,
    slot_id: UUID | None = None,
    status: ShipmentStatus = ShipmentStatus.CANCELLED,
) -> ShipmentResponse:
    return ShipmentResponse(
        id=shipment_id or uuid4(),
        order_id=order_id,
        carrier="Carrier",
        tracking_number=None,
        status=status,
        estimated_delivery=None,
        delivered_at=None,
        delivery_slot_id=slot_id,
    )


def write_result(response: object, status_code: int = 200) -> CommerceWriteResult[object]:
    return CommerceWriteResult(response, status_code, False)


@pytest.mark.parametrize(
    ("shipment_in_write_response", "shipment_in_read_back"),
    [(True, True), (False, False)],
)
def test_cancel_requires_exact_customer_order_status_and_response_shipment(
    shipment_in_write_response: bool,
    shipment_in_read_back: bool,
) -> None:
    order_id, customer_id = uuid4(), uuid4()
    proposal = CancelOrderProposal(order_id=order_id)
    shipment_id = uuid4()
    write_shipment = (
        shipment_response(order_id, shipment_id=shipment_id) if shipment_in_write_response else None
    )
    result = write_result(
        CancelOrderResponse(
            order=order_response(order_id, customer_id, OrderStatus.CANCELLED),
            shipment=write_shipment,
        )
    )
    readback = OrderShipmentReadBack(
        order=order_response(order_id, customer_id, OrderStatus.CANCELLED),
        shipment=(
            shipment_response(order_id, shipment_id=shipment_id) if shipment_in_read_back else None
        ),
    )

    verified = verify_postcondition(record_for(proposal, customer_id=customer_id), result, readback)

    assert verified.status is VerificationStatus.VERIFIED
    assert verified.verified_resource_id == order_id


def test_cancel_missing_or_wrong_customer_order_never_verifies() -> None:
    order_id, customer_id = uuid4(), uuid4()
    proposal = CancelOrderProposal(order_id=order_id)
    result = write_result(
        CancelOrderResponse(
            order=order_response(order_id, customer_id, OrderStatus.CANCELLED),
            shipment=None,
        )
    )

    missing = verify_postcondition(record_for(proposal, customer_id=customer_id), result, None)
    foreign = verify_postcondition(
        record_for(proposal, customer_id=customer_id),
        result,
        OrderShipmentReadBack(
            order=order_response(order_id, uuid4(), OrderStatus.CANCELLED),
            shipment=None,
        ),
    )

    assert missing.status is VerificationStatus.UNAVAILABLE
    assert foreign.status is VerificationStatus.MISMATCHED


def test_reschedule_requires_exact_shipment_id_order_and_requested_slot() -> None:
    order_id, slot_id, shipment_id = uuid4(), uuid4(), uuid4()
    proposal = RescheduleDeliveryProposal(order_id=order_id, delivery_slot_id=slot_id)
    action = record_for(proposal, resource_id=shipment_id)
    response = shipment_response(order_id, shipment_id=shipment_id, slot_id=slot_id)

    verified = verify_postcondition(action, write_result(response), response)
    wrong_slot = verify_postcondition(
        action,
        write_result(response),
        shipment_response(order_id, shipment_id=shipment_id, slot_id=uuid4()),
    )
    wrong_shipment = verify_postcondition(
        action,
        write_result(response),
        shipment_response(order_id, shipment_id=uuid4(), slot_id=slot_id),
    )

    assert verified.status is VerificationStatus.VERIFIED
    assert verified.verified_resource_id == shipment_id
    assert wrong_slot.status is VerificationStatus.MISMATCHED
    assert wrong_shipment.status is VerificationStatus.MISMATCHED


def test_return_requires_exact_return_order_items_values_and_initial_status() -> None:
    order_id, item_id, return_id = uuid4(), uuid4(), uuid4()
    proposal = ReturnProposal(
        order_id=order_id,
        reason="damaged",
        items=(ReturnItemProposal(order_item_id=item_id, quantity=2),),
    )
    response = ReturnResponse(
        id=return_id,
        order_id=order_id,
        reason="damaged",
        status=ReturnStatus.REQUESTED,
        created_at=NOW,
        updated_at=NOW,
        items=[ReturnItemResponse(id=uuid4(), order_item_id=item_id, quantity=2)],
    )
    action = record_for(proposal, resource_id=return_id)

    verified = verify_postcondition(action, write_result(response, 201), response)
    mismatch = verify_postcondition(
        action,
        write_result(response, 201),
        response.model_copy(
            update={"items": [ReturnItemResponse(id=uuid4(), order_item_id=item_id, quantity=1)]}
        ),
    )

    assert verified.status is VerificationStatus.VERIFIED
    assert verified.verified_resource_id == return_id
    assert mismatch.status is VerificationStatus.MISMATCHED


def test_ticket_requires_exact_id_customer_order_and_requested_fields() -> None:
    customer_id, order_id, ticket_id = uuid4(), uuid4(), uuid4()
    proposal = SupportTicketProposal(
        order_id=order_id,
        category=TicketCategory.DELIVERY,
        subject="Late delivery",
        description="Please help",
    )
    response = SupportTicketResponse(
        id=ticket_id,
        customer_id=customer_id,
        order_id=order_id,
        category=SupportTicketCategory.DELIVERY,
        subject="Late delivery",
        description="Please help",
        status=SupportTicketStatus.OPEN,
        created_at=NOW,
        updated_at=NOW,
    )
    action = record_for(proposal, customer_id=customer_id, resource_id=ticket_id)

    verified = verify_postcondition(action, write_result(response, 201), response)
    wrong_customer = verify_postcondition(
        action,
        write_result(response, 201),
        response.model_copy(update={"customer_id": uuid4()}),
    )
    wrong_description = verify_postcondition(
        action,
        write_result(response, 201),
        response.model_copy(update={"description": "different"}),
    )

    assert verified.status is VerificationStatus.VERIFIED
    assert verified.verified_resource_id == ticket_id
    assert wrong_customer.status is VerificationStatus.MISMATCHED
    assert wrong_description.status is VerificationStatus.MISMATCHED


def test_refund_requires_exact_refund_id_amount_reason_and_approved_request_state() -> None:
    order_id, refund_id = uuid4(), uuid4()
    proposal = RefundProposal(order_id=order_id, amount=Decimal("25.00"), reason="damaged")
    response = WriteRefundResponse(
        id=refund_id,
        amount=Decimal("25.00"),
        status=RefundStatus.APPROVED,
        reason="damaged",
        requires_manual_approval=False,
        created_at=NOW,
    )
    action = record_for(proposal, resource_id=refund_id)

    verified = verify_postcondition(
        action,
        write_result(response, 201),
        [
            RefundResponse(
                id=refund_id,
                amount="25.00",
                status=RefundStatus.APPROVED,
                reason="damaged",
                requires_manual_approval=False,
                created_at=NOW,
            )
        ],
    )
    pending = verify_postcondition(
        action,
        write_result(response, 201),
        [
            RefundResponse(
                id=refund_id,
                amount="25.00",
                status=RefundStatus.PENDING_MANUAL_APPROVAL,
                reason="damaged",
                requires_manual_approval=True,
                created_at=NOW,
            )
        ],
    )
    missing_id = verify_postcondition(action, write_result(response, 201), [])

    assert verified.status is VerificationStatus.VERIFIED
    assert verified.verified_resource_id == refund_id
    assert pending.status is VerificationStatus.MISMATCHED
    assert missing_id.status is VerificationStatus.UNAVAILABLE
