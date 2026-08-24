"""Tests for application-owned models matching the locked Commerce API."""

from datetime import date, datetime, time
from uuid import uuid4

import pytest
from pydantic import ValidationError

from verbaops.commerce.models import (
    DeliverySlotResponse,
    OrderResponse,
    ProductSearchResponse,
    RefundResponse,
    ShipmentResponse,
)


def test_commerce_models_parse_locked_read_payloads_and_preserve_money_strings() -> None:
    order_id = uuid4()
    customer_id = uuid4()
    product_id = uuid4()
    now = datetime(2026, 8, 24, 12, 0, tzinfo=datetime.now().astimezone().tzinfo)
    order = OrderResponse.model_validate(
        {
            "id": str(order_id),
            "customer_id": str(customer_id),
            "status": "confirmed",
            "total": "0012.3400",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "items": [
                {
                    "order_item_id": str(uuid4()),
                    "product_id": str(product_id),
                    "sku": "SKU-1",
                    "product_name": "Device",
                    "quantity": 1,
                    "unit_price": "0012.3400",
                    "line_total": "0012.3400",
                }
            ],
        }
    )

    assert order.id == order_id
    assert order.total == "0012.3400"
    assert order.items[0].unit_price == "0012.3400"


def test_shipment_refund_product_and_delivery_models_parse_contract_shapes() -> None:
    order_id = uuid4()
    shipment = ShipmentResponse.model_validate(
        {
            "id": str(uuid4()),
            "order_id": str(order_id),
            "carrier": "Carrier",
            "tracking_number": "TRACK-1",
            "status": "in_transit",
            "estimated_delivery": "2026-08-25T10:00:00Z",
            "delivered_at": None,
            "delivery_slot_id": None,
        }
    )
    refund = RefundResponse.model_validate(
        {
            "id": str(uuid4()),
            "amount": "0004.500",
            "status": "completed",
            "reason": "Damaged",
            "requires_manual_approval": False,
            "created_at": "2026-08-24T10:00:00Z",
        }
    )
    products = ProductSearchResponse.model_validate(
        {
            "items": [
                {
                    "id": str(uuid4()),
                    "sku": "SKU-1",
                    "name": "Device",
                    "description": "Description",
                    "price": "0004.500",
                    "stock": 3,
                }
            ],
            "limit": 1,
            "offset": 0,
            "has_more": False,
        }
    )
    slots = DeliverySlotResponse.model_validate(
        {
            "id": str(uuid4()),
            "service_date": "2026-08-25",
            "window_start": "09:00:00",
            "window_end": "11:00:00",
            "capacity": 10,
            "reserved_count": 2,
            "remaining_capacity": 8,
            "available": True,
        }
    )

    assert shipment.order_id == order_id
    assert refund.amount == "0004.500"
    assert products.items[0].price == "0004.500"
    assert slots.service_date == date(2026, 8, 25)
    assert slots.window_start == time(9, 0)


def test_commerce_models_reject_extra_fields() -> None:
    with pytest.raises(ValidationError):
        DeliverySlotResponse.model_validate(
            {
                "id": str(uuid4()),
                "service_date": "2026-08-25",
                "window_start": "09:00:00",
                "window_end": "11:00:00",
                "capacity": 10,
                "reserved_count": 2,
                "remaining_capacity": 8,
                "available": True,
                "unexpected": "nope",
            }
        )
