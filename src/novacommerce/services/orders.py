"""Focused ownership-constrained order, shipment, and refund reads."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from novacommerce.db.models.order import Order
from novacommerce.db.models.order_item import OrderItem
from novacommerce.db.models.refund import Refund
from novacommerce.db.models.shipment import Shipment


async def get_owned_order(
    session: AsyncSession, order_id: UUID, trusted_customer_id: UUID
) -> Order | None:
    result = await session.execute(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.product))
        .where(Order.id == order_id, Order.customer_id == trusted_customer_id)
    )
    return result.scalar_one_or_none()


async def get_owned_shipment(
    session: AsyncSession, order_id: UUID, trusted_customer_id: UUID
) -> Shipment | None:
    result = await session.execute(
        select(Shipment)
        .join(Order, Shipment.order_id == Order.id)
        .where(Shipment.order_id == order_id, Order.customer_id == trusted_customer_id)
    )
    return result.scalar_one_or_none()


async def get_owned_refunds(
    session: AsyncSession, order_id: UUID, trusted_customer_id: UUID
) -> list[Refund] | None:
    owner = await session.execute(
        select(Order.id).where(Order.id == order_id, Order.customer_id == trusted_customer_id)
    )
    if owner.scalar_one_or_none() is None:
        return None
    result = await session.execute(
        select(Refund)
        .where(Refund.order_id == order_id)
        .order_by(Refund.created_at.asc(), Refund.id.asc())
    )
    return list(result.scalars().all())
