"""Real PostgreSQL 16 contract coverage for the M2C read-only API."""

from collections.abc import AsyncIterator
from decimal import Decimal
from os import environ
from typing import Any
from uuid import UUID

import httpx
import pytest
import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from novacommerce.api.app import create_app
from novacommerce.config.settings import DatabaseSettings, Environment, Settings
from novacommerce.seed.config import SeedConfig
from novacommerce.seed.ids import scenario_uuid
from novacommerce.seed.service import seed_database

pytestmark = pytest.mark.integration

TOKEN = "m2c-integration-token-" + "x" * 32
TABLES = (
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


@pytest.fixture(scope="module")
def database_url() -> str:
    url = environ.get("NOVACOMMERCE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("NOVACOMMERCE_TEST_DATABASE_URL is not configured")
    if not url.startswith("postgresql+asyncpg://"):
        pytest.fail("M2C integration requires postgresql+asyncpg")
    return url


@pytest_asyncio.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    database_engine = create_async_engine(database_url, pool_pre_ping=True, echo=False)
    yield database_engine
    await database_engine.dispose()


async def clear_database(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        for table in TABLES:
            await connection.execute(text(f"DELETE FROM {table}"))


@pytest_asyncio.fixture
async def live_app(database_url: str, engine: AsyncEngine) -> AsyncIterator[Any]:
    await clear_database(engine)
    settings = Settings(
        environment=Environment.TEST,
        database=DatabaseSettings(url=SecretStr(database_url)),
        service_token=SecretStr(TOKEN),
    )
    await seed_database(settings, SeedConfig())
    app = create_app(settings=settings)
    async with app.router.lifespan_context(app):
        yield app
    await clear_database(engine)


async def call(
    app: Any,
    path: str,
    *,
    customer_id: UUID | None = None,
    token: str | None = TOKEN,
) -> httpx.Response:
    headers: dict[str, str] = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if customer_id is not None:
        headers["X-VerbaOps-Customer-ID"] = str(customer_id)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, headers=headers)


async def counts(engine: AsyncEngine) -> dict[str, int]:
    async with engine.connect() as connection:
        return {
            table: int(
                (await connection.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
            )
            for table in TABLES
        }


@pytest.mark.asyncio
async def test_m2c_customer_order_shipment_refund_auth_and_anti_enumeration(
    live_app: Any,
    engine: AsyncEngine,
) -> None:
    config = SeedConfig()
    primary = scenario_uuid(config, "customer_primary")
    other = scenario_uuid(config, "customer_other")
    cancellable = scenario_uuid(config, "order_cancellable")
    shipped = scenario_uuid(config, "order_already_shipped")
    protected = scenario_uuid(config, "order_refund_500_00")

    before = await counts(engine)
    own_customer = await call(live_app, f"/v1/customers/{primary}", customer_id=primary)
    foreign_customer = await call(live_app, f"/v1/customers/{other}", customer_id=primary)
    missing_customer = await call(
        live_app,
        "/v1/customers/00000000-0000-0000-0000-000000000000",
        customer_id=primary,
    )
    assert own_customer.status_code == 200
    assert foreign_customer.status_code == missing_customer.status_code == 404
    assert foreign_customer.json() == missing_customer.json()

    own_order = await call(live_app, f"/v1/orders/{cancellable}", customer_id=primary)
    foreign_order = await call(live_app, f"/v1/orders/{shipped}", customer_id=other)
    missing_order = await call(
        live_app,
        "/v1/orders/00000000-0000-0000-0000-000000000000",
        customer_id=primary,
    )
    assert own_order.status_code == 200
    order_body = own_order.json()
    assert Decimal(order_body["total"]) == sum(
        (Decimal(item["line_total"]) for item in order_body["items"]),
        start=Decimal("0.00"),
    )
    assert foreign_order.status_code == missing_order.status_code == 404
    assert foreign_order.json() == missing_order.json()

    owned_shipment = await call(live_app, f"/v1/orders/{shipped}/shipment", customer_id=primary)
    assert owned_shipment.status_code == 200
    async with engine.connect() as connection:
        pending = (
            await connection.execute(
                text(
                    "SELECT id, customer_id FROM orders "
                    "WHERE status = 'pending' ORDER BY id LIMIT 1"
                )
            )
        ).one()
        refund_owner = (
            await connection.execute(
                text(
                    "SELECT o.id, o.customer_id FROM orders o "
                    "JOIN refunds r ON r.order_id = o.id ORDER BY o.id LIMIT 1"
                )
            )
        ).one()
    pending_shipment = await call(
        live_app,
        f"/v1/orders/{pending.id}/shipment",
        customer_id=pending.customer_id,
    )
    assert pending_shipment.status_code == 404
    assert pending_shipment.json()["error"]["code"] == "shipment_not_found"
    owned_refund = await call(
        live_app,
        f"/v1/orders/{refund_owner.id}/refunds",
        customer_id=refund_owner.customer_id,
    )
    assert owned_refund.status_code == 200
    assert owned_refund.json()
    refunds = await call(live_app, f"/v1/orders/{protected}/refunds", customer_id=primary)
    assert refunds.status_code == 200
    assert refunds.json() == []

    unauthorized = await call(
        live_app, f"/v1/orders/{cancellable}", customer_id=primary, token=None
    )
    wrong = await call(live_app, f"/v1/orders/{cancellable}", customer_id=primary, token="wrong")
    assert unauthorized.status_code == wrong.status_code == 401
    assert unauthorized.json() == wrong.json()

    after = await counts(engine)
    assert after == before
    assert after["idempotency_records"] == 0
    assert after["commerce_events"] == 0


@pytest.mark.asyncio
async def test_m2c_product_search_and_canonical_delivery_slot_reads(
    live_app: Any,
    engine: AsyncEngine,
) -> None:
    config = SeedConfig()
    product_id = scenario_uuid(config, "product_500_00")
    available_id = scenario_uuid(config, "slot_available")
    one_remaining_id = scenario_uuid(config, "slot_one_remaining")
    full_id = scenario_uuid(config, "slot_full")
    before = await counts(engine)

    async with engine.connect() as connection:
        sku = str(
            (
                await connection.execute(
                    text("SELECT sku FROM products WHERE id = :id"), {"id": product_id}
                )
            ).scalar_one()
        )
    search = await call(live_app, f"/v1/products/search?q={sku}")
    assert search.status_code == 200
    assert search.json()["items"][0]["id"] == str(product_id)
    assert search.json()["items"][0]["price"] == "500.00"
    hostile = await call(live_app, r"/v1/products/search?q=%25")
    assert hostile.status_code == 200
    assert hostile.json()["items"] == []

    slots = await call(
        live_app,
        "/v1/delivery-slots?from_date=2026-08-21&to_date=2026-09-20&available_only=false",
    )
    assert slots.status_code == 200
    by_id = {item["id"]: item for item in slots.json()}
    assert by_id[str(available_id)]["remaining_capacity"] == 15
    assert by_id[str(available_id)]["available"] is True
    assert by_id[str(one_remaining_id)]["remaining_capacity"] == 1
    assert by_id[str(full_id)]["remaining_capacity"] == 0
    assert by_id[str(full_id)]["available"] is False

    available_only = await call(
        live_app,
        "/v1/delivery-slots?from_date=2026-08-21&to_date=2026-09-20",
    )
    assert full_id not in {item["id"] for item in available_only.json()}
    assert await counts(engine) == before
