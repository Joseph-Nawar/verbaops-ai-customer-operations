"""Shared response and event helpers for transactional writes."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from novacommerce.db.models.commerce_event import CommerceEvent
from novacommerce.db.models.order import Order
from novacommerce.db.models.order_item import OrderItem
from novacommerce.db.models.shipment import Shipment
from novacommerce.schemas.orders import OrderItemResponse, OrderResponse
from novacommerce.schemas.shipments import ShipmentResponse


def utc_now() -> datetime:
    return datetime.now(UTC)


def order_response(order: Order) -> OrderResponse:
    items = [
        OrderItemResponse(
            order_item_id=item.id,
            product_id=item.product_id,
            sku=item.product.sku,
            product_name=item.product.name,
            quantity=item.quantity,
            unit_price=item.unit_price,
            line_total=item.unit_price * item.quantity,
        )
        for item in order.items
    ]
    return OrderResponse(
        id=order.id,
        customer_id=order.customer_id,
        status=order.status,
        total=order.total,
        created_at=order.created_at,
        updated_at=order.updated_at,
        items=items,
    )


def shipment_response(shipment: Shipment) -> ShipmentResponse:
    return ShipmentResponse(
        id=shipment.id,
        order_id=shipment.order_id,
        carrier=shipment.carrier,
        tracking_number=shipment.tracking_number,
        status=shipment.status,
        estimated_delivery=shipment.estimated_delivery,
        delivered_at=shipment.delivered_at,
        delivery_slot_id=shipment.delivery_slot_id,
    )


async def append_event(
    session: AsyncSession,
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: UUID,
    customer_id: UUID,
    idempotency_key: str,
    payload: dict[str, Any],
) -> None:
    session.add(
        CommerceEvent(
            id=uuid4(),
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            customer_id=customer_id,
            idempotency_key=idempotency_key,
            payload=payload,
        )
    )


async def load_order_items(session: AsyncSession, order: Order) -> None:
    """Load products without relying on lazy IO after the response is built."""

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    result = await session.execute(
        select(OrderItem)
        .options(selectinload(OrderItem.product))
        .where(OrderItem.order_id == order.id)
        .order_by(OrderItem.id.asc())
    )
    order.items = list(result.scalars().all())
