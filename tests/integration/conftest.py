"""Shared isolation for real PostgreSQL integration tests."""

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

APPLICATION_TABLES = (
    "commerce_events",
    "idempotency_records",
    "support_tickets",
    "return_items",
    "returns",
    "refunds",
    "shipments",
    "order_items",
    "orders",
    "delivery_slots",
    "products",
    "customers",
)


async def reset_commerce_application_tables(engine: AsyncEngine) -> None:
    """Clear application rows without touching Commerce Alembic state."""

    async with engine.begin() as connection:
        for table in APPLICATION_TABLES:
            await connection.execute(text(f"DELETE FROM {table}"))


@pytest_asyncio.fixture(autouse=True)
async def isolate_commerce_test_state(engine: AsyncEngine) -> AsyncIterator[None]:
    """Reset each integration test before and after it when an engine exists."""

    await reset_commerce_application_tables(engine)
    yield
    await reset_commerce_application_tables(engine)
