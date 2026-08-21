"""Transactional order creation and cancellation."""

from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from novacommerce.db.models.delivery_slot import DeliverySlot
from novacommerce.db.models.order import Order, OrderStatus
from novacommerce.db.models.order_item import OrderItem
from novacommerce.db.models.product import Product
from novacommerce.db.models.shipment import Shipment, ShipmentStatus
from novacommerce.idempotency import WriteOutcome
from novacommerce.schemas.writes import CancelOrderResponse, CreateOrderResponse, OrderCreateRequest
from novacommerce.services.writes.common import (
    append_event,
    order_response,
    shipment_response,
    utc_now,
)
from novacommerce.services.writes.rules import cancellation_allowed


async def create_order(
    session: AsyncSession,
    *,
    customer_id: UUID,
    request: OrderCreateRequest,
    idempotency_key: str,
) -> WriteOutcome:
    product_ids = sorted((item.product_id for item in request.items), key=str)
    products = list(
        (
            await session.execute(
                select(Product)
                .where(Product.id.in_(product_ids))
                .order_by(Product.id.asc())
                .with_for_update()
            )
        ).scalars()
    )
    by_id = {product.id: product for product in products}
    if len(by_id) != len(product_ids) or any(
        not by_id[item.product_id].active for item in request.items if item.product_id in by_id
    ):
        return WriteOutcome(
            409,
            {
                "error": {
                    "code": "product_unavailable",
                    "message": "One or more products are unavailable.",
                }
            },
        )
    if any(by_id[item.product_id].stock < item.quantity for item in request.items):
        return WriteOutcome(
            409, {"error": {"code": "insufficient_stock", "message": "Insufficient product stock."}}
        )

    total = Decimal("0.00")
    order = Order(
        id=uuid4(), customer_id=customer_id, status=OrderStatus.CONFIRMED, total=Decimal("0.00")
    )
    session.add(order)
    items: list[OrderItem] = []
    for requested in request.items:
        product = by_id[requested.product_id]
        product.stock -= requested.quantity
        item = OrderItem(
            id=uuid4(),
            order_id=order.id,
            product_id=product.id,
            quantity=requested.quantity,
            unit_price=product.price,
            product=product,
        )
        items.append(item)
        total += product.price * requested.quantity
    order.total = total
    session.add_all(items)

    shipment = Shipment(
        id=uuid4(),
        order_id=order.id,
        carrier="NovaShip",
        tracking_number=f"NC-{uuid4().hex.upper()}",
        status=ShipmentStatus.PENDING,
        delivery_slot_id=None,
        estimated_delivery=None,
        delivered_at=None,
    )
    session.add(shipment)
    await session.flush()
    await append_event(
        session,
        event_type="order.created",
        aggregate_type="order",
        aggregate_id=order.id,
        customer_id=customer_id,
        idempotency_key=idempotency_key,
        payload={
            "order_id": str(order.id),
            "status": order.status.value,
            "total": format(total, ".2f"),
        },
    )
    body = CreateOrderResponse(
        order=order_response(order, items=items),
        shipment=shipment_response(shipment),
    )
    return WriteOutcome(201, body.model_dump(mode="json"))


async def cancel_order(
    session: AsyncSession,
    *,
    customer_id: UUID,
    order_id: UUID,
    idempotency_key: str,
) -> WriteOutcome:
    order = (
        await session.execute(
            select(Order)
            .where(Order.id == order_id, Order.customer_id == customer_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if order is None:
        return WriteOutcome(
            404, {"error": {"code": "resource_not_found", "message": "Resource not found."}}
        )
    shipment = (
        await session.execute(
            select(Shipment).where(Shipment.order_id == order.id).with_for_update()
        )
    ).scalar_one_or_none()
    if not cancellation_allowed(order.status, shipment.status if shipment is not None else None):
        return WriteOutcome(
            409,
            {"error": {"code": "order_not_cancellable", "message": "Order cannot be cancelled."}},
        )

    items = list(
        (
            await session.execute(
                select(OrderItem)
                .options(selectinload(OrderItem.product))
                .where(OrderItem.order_id == order.id)
                .order_by(OrderItem.product_id.asc())
                .with_for_update()
            )
        ).scalars()
    )
    product_ids = sorted({item.product_id for item in items}, key=str)
    products = list(
        (
            await session.execute(
                select(Product)
                .where(Product.id.in_(product_ids))
                .order_by(Product.id.asc())
                .with_for_update()
            )
        ).scalars()
    )
    products_by_id = {product.id: product for product in products}
    slot = None
    if shipment is not None and shipment.delivery_slot_id is not None:
        slot = (
            await session.execute(
                select(DeliverySlot)
                .where(DeliverySlot.id == shipment.delivery_slot_id)
                .with_for_update()
            )
        ).scalar_one()
    for item in items:
        products_by_id[item.product_id].stock += item.quantity
    if slot is not None:
        slot.reserved_count -= 1
    order.status = OrderStatus.CANCELLED
    order.cancelled_at = utc_now()
    if shipment is not None:
        shipment.status = ShipmentStatus.CANCELLED
    await session.flush()
    await append_event(
        session,
        event_type="order.cancelled",
        aggregate_type="order",
        aggregate_id=order.id,
        customer_id=customer_id,
        idempotency_key=idempotency_key,
        payload={"order_id": str(order.id), "status": order.status.value},
    )
    body = CancelOrderResponse(
        order=order_response(order, items=items),
        shipment=shipment_response(shipment) if shipment is not None else None,
    )
    return WriteOutcome(200, body.model_dump(mode="json"))
