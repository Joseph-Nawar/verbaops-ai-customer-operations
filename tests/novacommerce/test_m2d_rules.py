"""Pure M2D business-rule boundaries."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from novacommerce.db.models.order import OrderStatus
from novacommerce.db.models.refund import RefundStatus
from novacommerce.db.models.shipment import ShipmentStatus
from novacommerce.services.writes.rules import (
    cancellation_allowed,
    refund_decision,
    remaining_refundable,
    return_window_open,
)

ANCHOR = datetime(2026, 8, 21, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    "order_status",
    [OrderStatus.PENDING, OrderStatus.CONFIRMED, OrderStatus.PROCESSING],
)
@pytest.mark.parametrize(
    "shipment_status",
    [None, ShipmentStatus.PENDING, ShipmentStatus.LABEL_CREATED],
)
def test_cancellation_allows_each_locked_order_and_shipment_pair(
    order_status: OrderStatus,
    shipment_status: ShipmentStatus | None,
) -> None:
    assert cancellation_allowed(order_status, shipment_status)


@pytest.mark.parametrize(
    "order_status",
    [OrderStatus.SHIPPED, OrderStatus.DELIVERED, OrderStatus.CANCELLED],
)
@pytest.mark.parametrize(
    "shipment_status",
    [
        None,
        ShipmentStatus.PENDING,
        ShipmentStatus.LABEL_CREATED,
        ShipmentStatus.IN_TRANSIT,
        ShipmentStatus.OUT_FOR_DELIVERY,
        ShipmentStatus.DELIVERED,
        ShipmentStatus.EXCEPTION,
        ShipmentStatus.CANCELLED,
    ],
)
def test_cancellation_blocks_each_locked_terminal_order_pair(
    order_status: OrderStatus,
    shipment_status: ShipmentStatus | None,
) -> None:
    assert not cancellation_allowed(order_status, shipment_status)


@pytest.mark.parametrize(
    "order_status",
    [OrderStatus.PENDING, OrderStatus.CONFIRMED, OrderStatus.PROCESSING],
)
@pytest.mark.parametrize(
    "shipment_status",
    [
        ShipmentStatus.IN_TRANSIT,
        ShipmentStatus.OUT_FOR_DELIVERY,
        ShipmentStatus.DELIVERED,
        ShipmentStatus.EXCEPTION,
        ShipmentStatus.CANCELLED,
    ],
)
def test_cancellation_blocks_each_locked_non_cancellable_shipment_pair(
    order_status: OrderStatus,
    shipment_status: ShipmentStatus,
) -> None:
    assert not cancellation_allowed(order_status, shipment_status)


def test_return_window_is_inclusive_at_exactly_30_days() -> None:
    delivered = ANCHOR - timedelta(days=30)
    assert return_window_open(delivered, ANCHOR)
    assert not return_window_open(delivered, ANCHOR + timedelta(microseconds=1))
    assert not return_window_open(ANCHOR - timedelta(days=31), ANCHOR)


def test_refund_threshold_and_remaining_amount() -> None:
    assert refund_decision(Decimal("499.99")) == (RefundStatus.APPROVED, False)
    assert refund_decision(Decimal("500.00")) == (RefundStatus.APPROVED, False)
    assert refund_decision(Decimal("500.01")) == (
        RefundStatus.PENDING_MANUAL_APPROVAL,
        True,
    )
    assert remaining_refundable(
        Decimal("1000.00"), [Decimal("100.00"), Decimal("50.00")]
    ) == Decimal("850.00")
