"""Pure M2D business-rule boundaries."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

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


def test_cancellation_status_matrix() -> None:
    assert cancellation_allowed(OrderStatus.CONFIRMED, ShipmentStatus.LABEL_CREATED)
    assert cancellation_allowed(OrderStatus.PENDING, None)
    assert not cancellation_allowed(OrderStatus.SHIPPED, ShipmentStatus.IN_TRANSIT)
    assert not cancellation_allowed(OrderStatus.CONFIRMED, ShipmentStatus.OUT_FOR_DELIVERY)


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
