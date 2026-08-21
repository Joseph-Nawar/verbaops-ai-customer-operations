"""Customer-owned customer queries."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novacommerce.db.models.customer import Customer


async def get_owned_customer(
    session: AsyncSession, customer_id: UUID, trusted_customer_id: UUID
) -> Customer | None:
    result = await session.execute(
        select(Customer).where(Customer.id == customer_id, Customer.id == trusted_customer_id)
    )
    return result.scalar_one_or_none()
