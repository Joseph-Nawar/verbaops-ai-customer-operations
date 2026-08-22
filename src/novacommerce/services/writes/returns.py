"""Transactional customer return requests."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novacommerce.db.models.order import Order, OrderStatus
from novacommerce.db.models.order_item import OrderItem
from novacommerce.db.models.return_ import Return, ReturnItem, ReturnStatus
from novacommerce.db.models.shipment import Shipment, ShipmentStatus
from novacommerce.idempotency import WriteOutcome
from novacommerce.schemas.writes import ReturnCreateRequest, ReturnItemResponse, ReturnResponse
from novacommerce.services.writes.common import append_event, utc_now
from novacommerce.services.writes.rules import return_window_open


def _error(code: str, message: str) -> WriteOutcome:
    return WriteOutcome(409, {"error": {"code": code, "message": message}})


async def create_return(
    session: AsyncSession,
    *,
    customer_id: UUID,
    request: ReturnCreateRequest,
    idempotency_key: str,
    current_time: datetime | None = None,
) -> WriteOutcome:
    order = (
        await session.execute(
            select(Order)
            .where(Order.id == request.order_id, Order.customer_id == customer_id)
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
    now = current_time or utc_now()
    if (
        order.status != OrderStatus.DELIVERED
        or shipment is None
        or shipment.status != ShipmentStatus.DELIVERED
        or shipment.delivered_at is None
    ):
        return _error("return_not_allowed", "Return is not allowed for this order.")
    delivered_at = shipment.delivered_at
    if not return_window_open(delivered_at, now):
        return _error("return_window_expired", "The return window has expired.")

    requested_ids = sorted((item.order_item_id for item in request.items), key=str)
    order_items = list(
        (
            await session.execute(
                select(OrderItem)
                .where(OrderItem.order_id == order.id, OrderItem.id.in_(requested_ids))
                .order_by(OrderItem.id.asc())
                .with_for_update()
            )
        ).scalars()
    )
    by_id = {item.id: item for item in order_items}
    if len(by_id) != len(requested_ids):
        return _error("return_quantity_exceeded", "Return quantity exceeds the ordered quantity.")
    # Aggregate rows in Python so rejected returns remain excluded.
    consumed: dict[UUID, int] = {}
    rows = await session.execute(
        select(ReturnItem.order_item_id, ReturnItem.quantity)
        .join(Return, Return.id == ReturnItem.return_id)
        .where(
            Return.order_id == order.id,
            ReturnItem.order_item_id.in_(requested_ids),
            Return.status.in_(
                {
                    ReturnStatus.REQUESTED,
                    ReturnStatus.APPROVED,
                    ReturnStatus.RECEIVED,
                    ReturnStatus.COMPLETED,
                }
            ),
        )
    )
    for item_id, quantity in rows.all():
        consumed[item_id] = consumed.get(item_id, 0) + quantity
    for requested in request.items:
        if (
            consumed.get(requested.order_item_id, 0) + requested.quantity
            > by_id[requested.order_item_id].quantity
        ):
            return _error(
                "return_quantity_exceeded", "Return quantity exceeds the ordered quantity."
            )

    record = Return(
        id=uuid4(),
        order_id=order.id,
        reason=request.reason,
        status=ReturnStatus.REQUESTED,
    )
    items = [
        ReturnItem(
            id=uuid4(),
            return_id=record.id,
            order_item_id=item.order_item_id,
            quantity=item.quantity,
        )
        for item in request.items
    ]
    record.items = items
    session.add(record)
    await session.flush()
    await append_event(
        session,
        event_type="return.requested",
        aggregate_type="return",
        aggregate_id=record.id,
        customer_id=customer_id,
        idempotency_key=idempotency_key,
        payload={
            "return_id": str(record.id),
            "order_id": str(order.id),
            "status": record.status.value,
        },
    )
    body = ReturnResponse(
        id=record.id,
        order_id=record.order_id,
        reason=record.reason,
        status=record.status,
        created_at=record.created_at,
        updated_at=record.updated_at,
        items=[
            ReturnItemResponse(id=item.id, order_item_id=item.order_item_id, quantity=item.quantity)
            for item in items
        ],
    )
    return WriteOutcome(201, body.model_dump(mode="json"))
