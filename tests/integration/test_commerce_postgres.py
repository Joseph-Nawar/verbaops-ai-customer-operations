"""PostgreSQL-only NovaCommerce schema acceptance tests.

Set ``NOVACOMMERCE_TEST_DATABASE_URL`` to run these against a disposable
PostgreSQL 16 database. They intentionally do not use SQLite.
"""

from collections.abc import AsyncIterator
from decimal import Decimal
from os import environ
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from novacommerce.db.resources import DatabaseResources, ping_database

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.contract]


@pytest.fixture(scope="module")
def database_url() -> str:
    url = environ.get("NOVACOMMERCE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("NOVACOMMERCE_TEST_DATABASE_URL is not configured")
    if not url.startswith("postgresql+asyncpg://"):
        pytest.fail("integration acceptance requires postgresql+asyncpg")
    return url


@pytest_asyncio.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    resource = create_async_engine(database_url, pool_pre_ping=True, echo=False)
    yield resource
    await resource.dispose()


async def must_reject(engine: AsyncEngine, statement: str, **params: object) -> None:
    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await connection.execute(text(statement), params)


@pytest.mark.asyncio
async def test_exact_application_tables_exist(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        result = await connection.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' ORDER BY table_name"
            )
        )
    assert [row[0] for row in result] == [
        "alembic_version",
        "commerce_events",
        "customers",
        "delivery_slots",
        "idempotency_records",
        "order_items",
        "orders",
        "products",
        "refunds",
        "return_items",
        "returns",
        "shipments",
        "support_tickets",
    ]


@pytest.mark.asyncio
async def test_database_ping_succeeds_against_real_postgresql(engine: AsyncEngine) -> None:
    resources = DatabaseResources(engine, async_sessionmaker(engine, expire_on_commit=False))
    assert await ping_database(resources) is True


@pytest.mark.asyncio
async def test_foreign_keys_and_unique_constraints_are_enforced(engine: AsyncEngine) -> None:
    customer_id = uuid4()
    product_id = uuid4()
    order_id = uuid4()
    shipment_id = uuid4()
    sku = f"SKU-{product_id}"
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO customers (id, name, email, language, created_at) VALUES (:id, :name, :email, :language, now())"
            ),
            {
                "id": customer_id,
                "name": "Acceptance",
                "email": f"{customer_id}@example.com",
                "language": "en",
            },
        )
        await connection.execute(
            text(
                "INSERT INTO products (id, sku, name, description, price, stock, active, created_at, updated_at) VALUES (:id, :sku, :name, :description, :price, :stock, true, now(), now())"
            ),
            {
                "id": product_id,
                "sku": sku,
                "name": "Product",
                "description": "Test",
                "price": "12.34",
                "stock": 2,
            },
        )
        await connection.execute(
            text(
                "INSERT INTO orders (id, customer_id, status, total, created_at, updated_at) VALUES (:id, :customer_id, 'pending', 12.34, now(), now())"
            ),
            {"id": order_id, "customer_id": customer_id},
        )
        await connection.execute(
            text(
                "INSERT INTO shipments (id, order_id, carrier, tracking_number, status) VALUES (:id, :order_id, 'carrier', :tracking, 'pending')"
            ),
            {"id": shipment_id, "order_id": order_id, "tracking": f"TRACK-{shipment_id}"},
        )
    await must_reject(
        engine,
        "INSERT INTO orders (id, customer_id, status, total, created_at, updated_at) VALUES (:id, :customer_id, 'pending', 1, now(), now())",
        id=uuid4(),
        customer_id=uuid4(),
    )
    await must_reject(
        engine,
        "INSERT INTO customers (id, name, email, language, created_at) VALUES (:id, 'Duplicate', :email, 'en', now())",
        id=uuid4(),
        email=f"{customer_id}@example.com",
    )
    await must_reject(
        engine,
        "INSERT INTO shipments (id, order_id, carrier, tracking_number, status) VALUES (:id, :order_id, 'carrier', :tracking, 'pending')",
        id=uuid4(),
        order_id=order_id,
        tracking=f"TRACK-{shipment_id}",
    )
    await must_reject(
        engine,
        "INSERT INTO products (id, sku, name, description, price, stock, active, created_at, updated_at) VALUES (:id, :sku, 'Duplicate', 'Duplicate', 1, 1, true, now(), now())",
        id=uuid4(),
        sku=sku,
    )


@pytest.mark.asyncio
async def test_check_constraints_and_decimal_round_trip(engine: AsyncEngine) -> None:
    product_id = uuid4()
    await must_reject(
        engine,
        "INSERT INTO products (id, sku, name, description, price, stock, active, created_at, updated_at) VALUES (:id, :sku, 'Bad', 'Bad', -1, 1, true, now(), now())",
        id=product_id,
        sku=f"NEG-PRICE-{product_id}",
    )
    await must_reject(
        engine,
        "INSERT INTO products (id, sku, name, description, price, stock, active, created_at, updated_at) VALUES (:id, :sku, 'Bad', 'Bad', 1, -1, true, now(), now())",
        id=uuid4(),
        sku=f"NEG-STOCK-{product_id}",
    )
    await must_reject(
        engine,
        "INSERT INTO delivery_slots (id, service_date, window_start, window_end, capacity, reserved_count) VALUES (:id, current_date, '09:00', '10:00', 1, 2)",
        id=uuid4(),
    )
    customer_id = uuid4()
    order_id = uuid4()
    valid_product_id = uuid4()
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO customers (id, name, email, language, created_at) VALUES (:id, 'Quantity', :email, 'en', now())"
            ),
            {"id": customer_id, "email": f"{customer_id}@example.com"},
        )
        await connection.execute(
            text(
                "INSERT INTO products (id, sku, name, description, price, stock, active, created_at, updated_at) VALUES (:id, :sku, 'Quantity', 'Quantity', 1, 1, true, now(), now())"
            ),
            {"id": valid_product_id, "sku": f"QUANTITY-{valid_product_id}"},
        )
        await connection.execute(
            text(
                "INSERT INTO orders (id, customer_id, status, total, created_at, updated_at) VALUES (:id, :customer_id, 'pending', 1, now(), now())"
            ),
            {"id": order_id, "customer_id": customer_id},
        )
    await must_reject(
        engine,
        "INSERT INTO order_items (id, order_id, product_id, quantity, unit_price) VALUES (:id, :order_id, :product_id, 0, 1)",
        id=uuid4(),
        order_id=order_id,
        product_id=valid_product_id,
    )
    async with engine.begin() as connection:
        result = await connection.execute(text("SELECT CAST(12.34 AS NUMERIC(12, 2)) AS amount"))
    assert result.scalar_one() == Decimal("12.34")
