"""Small pure business-rule functions shared by write services and tests."""

from datetime import datetime, timedelta
from decimal import Decimal

from novacommerce.db.models.order import OrderStatus
from novacommerce.db.models.refund import RefundStatus
from novacommerce.db.models.shipment import ShipmentStatus


def cancellation_allowed(order_status: OrderStatus, shipment_status: ShipmentStatus | None) -> bool:
    return order_status in {
        OrderStatus.PENDING,
        OrderStatus.CONFIRMED,
        OrderStatus.PROCESSING,
    } and shipment_status in {None, ShipmentStatus.PENDING, ShipmentStatus.LABEL_CREATED}


def return_window_open(delivered_at: datetime, current_time: datetime) -> bool:
    return current_time <= delivered_at + timedelta(days=30)


def refund_decision(amount: Decimal) -> tuple[RefundStatus, bool]:
    manual = amount > Decimal("500.00")
    return (
        RefundStatus.PENDING_MANUAL_APPROVAL if manual else RefundStatus.APPROVED,
        manual,
    )


def remaining_refundable(total: Decimal, committed_amounts: list[Decimal]) -> Decimal:
    return total - sum(committed_amounts, Decimal("0.00"))
