"""Pure request and response contracts for M2D writes."""

from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import pytest
from pydantic import ValidationError

from novacommerce.schemas.writes import (
    OrderCreateRequest,
    RefundCreateRequest,
    ReturnCreateRequest,
    SupportTicketCreateRequest,
)

PRODUCT = UUID("00000000-0000-0000-0000-000000000001")
ITEM = UUID("00000000-0000-0000-0000-000000000002")
ORDER = UUID("00000000-0000-0000-0000-000000000003")


def test_order_request_rejects_client_owned_fields_and_duplicate_products() -> None:
    with pytest.raises(ValidationError):
        OrderCreateRequest.model_validate(
            cast(
                Any,
                {
                    "customer_id": str(ORDER),
                    "items": [
                        {"product_id": str(PRODUCT), "quantity": 1},
                        {"product_id": str(PRODUCT), "quantity": 2},
                    ],
                },
            )
        )


def test_order_request_enforces_item_and_quantity_bounds() -> None:
    with pytest.raises(ValidationError):
        OrderCreateRequest(items=[])
    with pytest.raises(ValidationError):
        OrderCreateRequest(items=cast(Any, [{"product_id": PRODUCT, "quantity": 0}]))


def test_reason_subject_and_description_trim_and_reject_blank() -> None:
    refund = RefundCreateRequest(amount=Decimal("499.99"), reason="  valid  ")
    assert refund.reason == "valid"
    ticket = SupportTicketCreateRequest(subject=" subject ", description=" description ")
    assert ticket.subject == "subject"
    assert ticket.description == "description"
    with pytest.raises(ValidationError):
        RefundCreateRequest(amount=Decimal("1.00"), reason="   ")
    with pytest.raises(ValidationError):
        SupportTicketCreateRequest(subject=" ", description="description")


def test_return_request_rejects_duplicate_lines_and_trims_reason() -> None:
    with pytest.raises(ValidationError):
        ReturnCreateRequest(
            order_id=ORDER,
            reason=" reason ",
            items=cast(
                Any,
                [
                    {"order_item_id": ITEM, "quantity": 1},
                    {"order_item_id": ITEM, "quantity": 1},
                ],
            ),
        )
