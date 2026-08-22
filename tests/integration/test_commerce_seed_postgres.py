"""Real PostgreSQL 16 integration coverage for the deterministic seed service."""

from collections.abc import AsyncIterator
from os import environ

import pytest
import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from novacommerce.config.settings import DatabaseSettings, Environment, Settings
from novacommerce.seed.config import SeedConfig
from novacommerce.seed.service import SeedResult, SeedServiceError, seed_database

pytestmark = pytest.mark.integration

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
        pytest.fail("seed integration requires postgresql+asyncpg")
    return url


@pytest_asyncio.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    database_engine = create_async_engine(database_url, pool_pre_ping=True, echo=False)
    yield database_engine
    await database_engine.dispose()


@pytest_asyncio.fixture
async def clean_database(engine: AsyncEngine) -> AsyncIterator[None]:
    async with engine.begin() as connection:
        for table in TABLES:
            await connection.execute(text(f"DELETE FROM {table}"))
    yield
    async with engine.begin() as connection:
        for table in TABLES:
            await connection.execute(text(f"DELETE FROM {table}"))


async def _seed(
    url: str, *, reset: bool = False, failure_after_batches: int | None = None
) -> SeedResult:
    return await seed_database(
        Settings(
            environment=Environment.TEST,
            database=DatabaseSettings(url=SecretStr(url)),
        ),
        SeedConfig(),
        reset=reset,
        failure_after_batches=failure_after_batches,
    )


async def _counts(engine: AsyncEngine) -> dict[str, int]:
    result: dict[str, int] = {}
    async with engine.connect() as connection:
        for table in reversed(TABLES):
            result[table] = int(
                (await connection.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
            )
    return result


@pytest.mark.asyncio
async def test_empty_migrated_database_seeds_successfully_with_exact_counts(
    database_url: str, engine: AsyncEngine, clean_database: None
) -> None:
    result = await _seed(database_url)
    counts = await _counts(engine)
    assert counts == {
        "customers": 1_000,
        "products": 2_000,
        "orders": 10_000,
        "order_items": 25_000,
        "shipments": 9_200,
        "delivery_slots": 180,
        "refunds": 800,
        "returns": 600,
        "return_items": 900,
        "support_tickets": 500,
        "idempotency_records": 0,
        "commerce_events": 0,
    }
    assert result.counts == counts


@pytest.mark.asyncio
async def test_database_invariants_decimal_totals_and_slot_reservations(
    database_url: str, engine: AsyncEngine, clean_database: None
) -> None:
    await _seed(database_url)
    async with engine.connect() as connection:
        invalid_totals = await connection.execute(
            text(
                "SELECT count(*) FROM orders o WHERE o.total != (SELECT coalesce(sum(i.unit_price * i.quantity), 0) FROM order_items i WHERE i.order_id = o.id)"
            )
        )
        invalid_slots = await connection.execute(
            text(
                "SELECT count(*) FROM delivery_slots s WHERE s.reserved_count != (SELECT count(*) FROM shipments h WHERE h.delivery_slot_id = s.id)"
            )
        )
        round_trip = await connection.execute(
            text("SELECT amount FROM refunds ORDER BY amount LIMIT 1")
        )
    assert invalid_totals.scalar_one() == 0
    assert invalid_slots.scalar_one() == 0
    assert str(round_trip.scalar_one()) == "1.00"


@pytest.mark.asyncio
async def test_non_empty_seed_refuses_without_changing_counts(
    database_url: str, engine: AsyncEngine, clean_database: None
) -> None:
    await _seed(database_url)
    before = await _counts(engine)
    with pytest.raises(SeedServiceError, match="not empty"):
        await _seed(database_url)
    assert await _counts(engine) == before


@pytest.mark.asyncio
async def test_reset_reproduces_canonical_ids_counts_and_fingerprint(
    database_url: str, engine: AsyncEngine, clean_database: None
) -> None:
    first = await _seed(database_url)
    async with engine.connect() as connection:
        first_customer = (
            await connection.execute(text("SELECT id FROM customers ORDER BY email LIMIT 1"))
        ).scalar_one()
        first_order = (
            await connection.execute(text("SELECT id FROM orders WHERE total = 500.00"))
        ).scalar_one()
    second = await _seed(database_url, reset=True)
    async with engine.connect() as connection:
        second_customer = (
            await connection.execute(text("SELECT id FROM customers ORDER BY email LIMIT 1"))
        ).scalar_one()
        second_order = (
            await connection.execute(text("SELECT id FROM orders WHERE total = 500.00"))
        ).scalar_one()
    assert second.fingerprint == first.fingerprint
    assert second.counts == first.counts
    assert second_customer == first_customer
    assert second_order == first_order


@pytest.mark.asyncio
async def test_forced_mid_seed_failure_rolls_back_every_application_table(
    database_url: str, engine: AsyncEngine, clean_database: None
) -> None:
    with pytest.raises(SeedServiceError, match="forced mid-seed"):
        await _seed(database_url, failure_after_batches=3)
    assert all(value == 0 for value in (await _counts(engine)).values())


@pytest.mark.asyncio
async def test_staging_and_production_seeding_are_refused(
    database_url: str, engine: AsyncEngine, clean_database: None
) -> None:
    for environment in (Environment.STAGING, Environment.PRODUCTION):
        with pytest.raises(SeedServiceError, match="only in development or test"):
            await seed_database(
                Settings(
                    environment=environment,
                    database=DatabaseSettings(url=SecretStr(database_url)),
                    service_token=SecretStr("m2d-seed-integration-token-" + "x" * 32),
                ),
                SeedConfig(),
            )
    assert all(value == 0 for value in (await _counts(engine)).values())


@pytest.mark.asyncio
async def test_named_scenario_rows_have_expected_database_state(
    database_url: str, engine: AsyncEngine, clean_database: None
) -> None:
    result = await _seed(database_url)
    async with engine.connect() as connection:
        cancellable = await connection.execute(
            text(
                "SELECT o.status, s.status FROM orders o JOIN shipments s ON s.order_id = o.id WHERE o.id = :id"
            ),
            {"id": result.scenario_ids["order_cancellable"]},
        )
        refund_order = await connection.execute(
            text("SELECT total FROM orders WHERE id = :id"),
            {"id": result.scenario_ids["order_refund_500_00"]},
        )
        protected_refunds = await connection.execute(
            text("SELECT count(*) FROM refunds WHERE order_id IN (:a, :b, :c)"),
            {
                "a": result.scenario_ids["order_refund_499_99"],
                "b": result.scenario_ids["order_refund_500_00"],
                "c": result.scenario_ids["order_refund_501_00"],
            },
        )
    assert tuple(cancellable.one()) == ("confirmed", "label_created")
    assert str(refund_order.scalar_one()) == "500.00"
    assert protected_refunds.scalar_one() == 0
