"""Transactional PostgreSQL seed service using SQLAlchemy Core bulk inserts."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, insert, text
from sqlalchemy.ext.asyncio import AsyncConnection

from novacommerce.config.settings import Environment, Settings
from novacommerce.db import models as _models  # noqa: F401  # register metadata
from novacommerce.db.base import Base
from novacommerce.db.resources import create_database_resources
from novacommerce.seed.config import SeedConfig
from novacommerce.seed.generator import SeedDataset, generate_dataset

BUSINESS_TABLES = (
    "customers",
    "products",
    "orders",
    "order_items",
    "shipments",
    "delivery_slots",
    "refunds",
    "returns",
    "return_items",
    "support_tickets",
    "idempotency_records",
    "commerce_events",
)
RESET_ORDER = (
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


class SeedServiceError(RuntimeError):
    """Raised when the administrative seed operation is refused or fails."""


@dataclass(frozen=True, slots=True)
class SeedResult:
    """Safe summary returned after a committed seed transaction."""

    seed: int
    as_of: str
    counts: dict[str, int]
    fingerprint: str
    scenario_ids: dict[str, str]


async def _database_has_business_data(connection: AsyncConnection) -> bool:
    for table_name in BUSINESS_TABLES:
        result = await connection.execute(
            text(f"SELECT EXISTS (SELECT 1 FROM {table_name} LIMIT 1)")
        )
        if bool(result.scalar_one()):
            return True
    return False


async def _reset_database(connection: AsyncConnection) -> None:
    for table_name in RESET_ORDER:
        await connection.execute(delete(Base.metadata.tables[table_name]))


async def _insert_rows(
    connection: AsyncConnection,
    dataset: SeedDataset,
    *,
    failure_after_batches: int | None = None,
) -> None:
    table_rows = (
        ("customers", dataset.customers),
        ("products", dataset.products),
        ("orders", dataset.orders),
        ("order_items", dataset.order_items),
        ("delivery_slots", dataset.delivery_slots),
        ("shipments", dataset.shipments),
        ("refunds", dataset.refunds),
        ("returns", dataset.returns),
        ("return_items", dataset.return_items),
        ("support_tickets", dataset.support_tickets),
        ("idempotency_records", dataset.idempotency_records),
        ("commerce_events", dataset.commerce_events),
    )
    batches = 0
    for table_name, rows in table_rows:
        table = Base.metadata.tables[table_name]
        for start in range(0, len(rows), 750):
            batch = rows[start : start + 750]
            if not batch:
                continue
            await connection.execute(insert(table), batch)
            batches += 1
            if failure_after_batches is not None and batches >= failure_after_batches:
                raise SeedServiceError("forced mid-seed failure for rollback verification")


async def seed_database(
    settings: Settings,
    config: SeedConfig,
    *,
    reset: bool = False,
    failure_after_batches: int | None = None,
) -> SeedResult:
    """Generate and atomically insert a canonical dataset into PostgreSQL."""

    if settings.environment not in (Environment.DEVELOPMENT, Environment.TEST):
        raise SeedServiceError("NovaCommerce seeding is permitted only in development or test")
    dataset = generate_dataset(config)
    resources = create_database_resources(settings)
    try:
        async with resources.engine.begin() as connection:
            if await _database_has_business_data(connection):
                if not reset:
                    raise SeedServiceError(
                        "NovaCommerce database is not empty; refusing seed without --reset"
                    )
                await _reset_database(connection)
            await _insert_rows(
                connection,
                dataset,
                failure_after_batches=failure_after_batches,
            )
    finally:
        await resources.engine.dispose()
    return SeedResult(
        seed=dataset.seed,
        as_of=dataset.as_of.isoformat(),
        counts=dataset.counts,
        fingerprint=dataset.fingerprint,
        scenario_ids={key: str(value) for key, value in dataset.scenario_ids.items()},
    )
