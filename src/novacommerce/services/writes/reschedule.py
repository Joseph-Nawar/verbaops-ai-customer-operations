"""Transactional shipment delivery-slot changes."""

from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novacommerce.db.models.delivery_slot import DeliverySlot
from novacommerce.db.models.order import Order, OrderStatus
from novacommerce.db.models.shipment import Shipment, ShipmentStatus
from novacommerce.idempotency import WriteOutcome
from novacommerce.schemas.writes import RescheduleRequest
from novacommerce.services.writes.common import append_event, shipment_response


def _error(code: str, message: str) -> WriteOutcome:
    return WriteOutcome(409, {"error": {"code": code, "message": message}})


async def reschedule_shipment(
    session: AsyncSession,
    *,
    customer_id: UUID,
    order_id: UUID,
    request: RescheduleRequest,
    idempotency_key: str,
    current_date: date | None = None,
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
    if (
        shipment is None
        or order.status not in {OrderStatus.CONFIRMED, OrderStatus.PROCESSING, OrderStatus.SHIPPED}
        or shipment.status
        not in {
            ShipmentStatus.PENDING,
            ShipmentStatus.LABEL_CREATED,
            ShipmentStatus.IN_TRANSIT,
        }
    ):
        return _error("shipment_not_reschedulable", "Shipment cannot be rescheduled.")

    current_slot_id = shipment.delivery_slot_id
    target_slot_id = request.delivery_slot_id
    slot_ids = sorted(
        {slot_id for slot_id in (current_slot_id, target_slot_id) if slot_id is not None}, key=str
    )
    slots = list(
        (
            await session.execute(
                select(DeliverySlot)
                .where(DeliverySlot.id.in_(slot_ids))
                .order_by(DeliverySlot.id.asc())
                .with_for_update()
            )
        ).scalars()
    )
    by_id = {slot.id: slot for slot in slots}
    target = by_id.get(target_slot_id)
    if target is None:
        return _error("delivery_slot_not_found", "Delivery slot not found.")
    today = current_date or datetime.now(UTC).date()
    if target.service_date < today:
        return _error("delivery_slot_not_valid", "Delivery slot is not valid.")
    if current_slot_id == target_slot_id:
        return WriteOutcome(200, shipment_response(shipment).model_dump(mode="json"))
    if target.reserved_count >= target.capacity:
        return _error("delivery_slot_full", "Delivery slot is full.")

    old = by_id.get(current_slot_id) if current_slot_id is not None else None
    target.reserved_count += 1
    if old is not None:
        if old.reserved_count <= 0:
            return _error("shipment_not_reschedulable", "Shipment reservation is invalid.")
        old.reserved_count -= 1
    shipment.delivery_slot_id = target.id
    shipment.estimated_delivery = datetime.combine(
        target.service_date, target.window_end, tzinfo=UTC
    )
    await session.flush()
    await append_event(
        session,
        event_type="shipment.rescheduled",
        aggregate_type="shipment",
        aggregate_id=shipment.id,
        customer_id=customer_id,
        idempotency_key=idempotency_key,
        payload={
            "shipment_id": str(shipment.id),
            "order_id": str(order.id),
            "delivery_slot_id": str(target.id),
        },
    )
    return WriteOutcome(200, shipment_response(shipment).model_dump(mode="json"))
