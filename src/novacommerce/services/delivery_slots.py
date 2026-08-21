"""Delivery-slot reads with availability derived at response time."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novacommerce.clock import UTCClock, delivery_date_range
from novacommerce.db.models.delivery_slot import DeliverySlot


async def list_delivery_slots(
    session: AsyncSession,
    clock: UTCClock,
    *,
    from_date: date | None,
    to_date: date | None,
    available_only: bool,
) -> list[DeliverySlot]:
    start, end = delivery_date_range(clock, from_date=from_date, to_date=to_date)
    statement = (
        select(DeliverySlot)
        .where(DeliverySlot.service_date.between(start, end))
        .order_by(
            DeliverySlot.service_date.asc(),
            DeliverySlot.window_start.asc(),
            DeliverySlot.id.asc(),
        )
    )
    if available_only:
        statement = statement.where(DeliverySlot.reserved_count < DeliverySlot.capacity)
    result = await session.execute(statement)
    return list(result.scalars().all())
