from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from verbaops.actions.models import (
    ActionProposal,
    ActionState,
    ActionType,
    CancelOrderProposal,
    RefundProposal,
    RescheduleDeliveryProposal,
    ReturnProposal,
    SupportTicketProposal,
    TicketCategory,
)


def _proposal_cases() -> tuple[tuple[type[BaseModel], dict[str, Any]], ...]:
    order_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    item_id = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    slot_id = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
    return (
        (
            RescheduleDeliveryProposal,
            {
                "action_type": "reschedule_delivery",
                "order_id": order_id,
                "delivery_slot_id": slot_id,
            },
        ),
        (CancelOrderProposal, {"action_type": "cancel_order", "order_id": order_id}),
        (
            ReturnProposal,
            {
                "action_type": "initiate_return",
                "order_id": order_id,
                "items": ({"order_item_id": item_id, "quantity": 1},),
                "reason": "Changed my mind",
            },
        ),
        (
            SupportTicketProposal,
            {
                "action_type": "create_support_ticket",
                "order_id": order_id,
                "category": TicketCategory.ORDER,
                "subject": "Delivery update",
                "description": "Please check delivery status.",
            },
        ),
        (
            RefundProposal,
            {
                "action_type": "request_refund",
                "order_id": order_id,
                "amount": Decimal("500.00"),
                "reason": "Duplicate charge",
            },
        ),
    )


@pytest.mark.parametrize(
    "forbidden_field",
    [
        "tenant_id",
        "customer_id",
        "principal_id",
        "roles",
        "state",
        "confirmation_required",
        "approval_required",
        "currency",
        "idempotency_key",
        "execute",
        "approval_reference",
        "endpoint",
        "unknown_field",
    ],
)
def test_action_payloads_forbid_identity_and_unknown_fields(forbidden_field: str) -> None:
    for model, payload in _proposal_cases():
        attempted = {**payload, forbidden_field: "caller-controlled"}
        with pytest.raises(ValidationError):
            model.model_validate(attempted)


def test_proposal_union_selects_only_the_declared_action_type() -> None:
    proposal: ActionProposal = TypeAdapter(ActionProposal).validate_python(_proposal_cases()[0][1])
    assert proposal.action_type is ActionType.RESCHEDULE_DELIVERY
    assert isinstance(proposal, RescheduleDeliveryProposal)


def test_return_items_are_nonempty_distinct_and_positive() -> None:
    order_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    first = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    second = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
    base = {"action_type": "initiate_return", "order_id": order_id, "reason": "Wrong size"}

    with pytest.raises(ValidationError):
        ReturnProposal.model_validate({**base, "items": ()})
    with pytest.raises(ValidationError):
        ReturnProposal.model_validate(
            {
                **base,
                "items": (
                    {"order_item_id": first, "quantity": 1},
                    {"order_item_id": first, "quantity": 2},
                ),
            }
        )
    with pytest.raises(ValidationError):
        ReturnProposal.model_validate(
            {**base, "items": ({"order_item_id": second, "quantity": 0},)}
        )


def test_refund_amount_is_a_positive_canonical_currency_decimal() -> None:
    order_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    base = {"action_type": "request_refund", "order_id": order_id, "reason": "Duplicate"}

    assert RefundProposal.model_validate({**base, "amount": Decimal("500.00")}).amount == Decimal(
        "500.00"
    )
    with pytest.raises(ValidationError):
        RefundProposal.model_validate({**base, "amount": Decimal("0.00")})
    with pytest.raises(ValidationError):
        RefundProposal.model_validate({**base, "amount": Decimal("1.001")})
    assert [member.value for member in TicketCategory] == [
        "order",
        "delivery",
        "returns_refunds",
        "product",
        "warranty",
        "payment",
        "account",
        "other",
    ]


def test_action_state_vocabulary_is_exactly_frozen() -> None:
    assert {state.value for state in ActionState} == {
        "proposed",
        "policy_denied",
        "awaiting_approval",
        "awaiting_confirmation",
        "ready_to_execute",
        "executing",
        "succeeded",
        "rejected",
        "failed",
        "unresolved",
        "expired",
    }


def test_action_types_are_a_closed_wire_contract() -> None:
    assert {action_type.value for action_type in ActionType} == {
        "reschedule_delivery",
        "cancel_order",
        "initiate_return",
        "create_support_ticket",
        "request_refund",
    }
