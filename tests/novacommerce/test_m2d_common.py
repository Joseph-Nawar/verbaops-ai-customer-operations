"""Pure contracts for shared M2D response and event helpers."""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest

from novacommerce.db.models.shipment import ShipmentStatus
from novacommerce.services.writes.common import (
    append_event,
    order_response,
    shipment_response,
    utc_now,
)

CUSTOMER = UUID("00000000-0000-0000-0000-000000000001")
ORDER = UUID("00000000-0000-0000-0000-000000000002")
ITEM = UUID("00000000-0000-0000-0000-000000000003")
PRODUCT = UUID("00000000-0000-0000-0000-000000000004")
SHIPMENT = UUID("00000000-0000-0000-0000-000000000005")


def make_item() -> Any:
    return SimpleNamespace(
        id=ITEM,
        product_id=PRODUCT,
        product=SimpleNamespace(sku="SKU-1", name="Product 1"),
        quantity=2,
        unit_price=Decimal("4.25"),
    )


def make_order(item: Any) -> Any:
    now = datetime(2026, 8, 21, 12, tzinfo=UTC)
    return SimpleNamespace(
        id=ORDER,
        customer_id=CUSTOMER,
        status="confirmed",
        total=Decimal("8.50"),
        created_at=now,
        updated_at=now,
        items=[item],
    )


def test_order_response_derives_decimal_line_total_from_relationship_items() -> None:
    response = order_response(cast(Any, make_order(make_item())))
    assert response.items[0].line_total == Decimal("8.50")
    assert response.total == Decimal("8.50")


def test_shipment_response_maps_nullable_delivery_fields() -> None:
    response = shipment_response(
        cast(
            Any,
            SimpleNamespace(
                id=SHIPMENT,
                order_id=ORDER,
                carrier="NovaShip",
                tracking_number="NC-TRACK-1",
                status=ShipmentStatus.PENDING,
                estimated_delivery=None,
                delivered_at=None,
                delivery_slot_id=None,
            ),
        )
    )
    assert response.id == SHIPMENT
    assert response.status == ShipmentStatus.PENDING
    assert response.delivery_slot_id is None


@pytest.mark.asyncio
async def test_append_event_adds_customer_scoped_event_without_committing() -> None:
    class FakeSession:
        def __init__(self) -> None:
            self.values: list[Any] = []

        def add(self, value: Any) -> None:
            self.values.append(value)

    session = FakeSession()
    await append_event(
        cast(Any, session),
        event_type="order.created",
        aggregate_type="order",
        aggregate_id=ORDER,
        customer_id=CUSTOMER,
        idempotency_key="m2d-event-001",
        payload={"order_id": str(ORDER)},
    )
    assert len(session.values) == 1
    assert session.values[0].event_type == "order.created"
    assert session.values[0].customer_id == CUSTOMER


def test_utc_now_is_timezone_aware_utc() -> None:
    now = utc_now()
    assert now.tzinfo == UTC
