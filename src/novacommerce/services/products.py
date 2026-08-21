"""Active product search with literal escaped PostgreSQL matching."""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from novacommerce.auth.service import escape_like_literal
from novacommerce.db.models.product import Product


async def search_products(
    session: AsyncSession, query: str, limit: int, offset: int
) -> tuple[list[Product], bool]:
    pattern = f"%{escape_like_literal(query)}%"
    statement = (
        select(Product)
        .where(
            Product.active.is_(True),
            or_(
                Product.sku.ilike(pattern, escape="\\"),
                Product.name.ilike(pattern, escape="\\"),
                Product.description.ilike(pattern, escape="\\"),
            ),
        )
        .order_by(Product.sku.asc(), Product.id.asc())
        .offset(offset)
        .limit(limit + 1)
    )
    result = await session.execute(statement)
    rows = list(result.scalars().all())
    return rows[:limit], len(rows) > limit
