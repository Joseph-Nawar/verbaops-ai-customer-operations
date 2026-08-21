"""Async Alembic environment for the isolated NovaCommerce database."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from novacommerce.config.settings import Settings
from novacommerce.db import Base
from novacommerce.db import models as _models  # noqa: F401  # register model metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def configured_url() -> str:
    url = Settings().database.url
    if url is None or not url.get_secret_value().strip():
        raise RuntimeError("NovaCommerce database URL is required for migrations")
    return url.get_secret_value()


def run_migrations_offline() -> None:
    """Run NovaCommerce migrations without an engine."""

    context.configure(
        url=configured_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create a short-lived migration engine from NovaCommerce settings."""

    connectable = async_engine_from_config(
        {"sqlalchemy.url": configured_url()},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        echo=False,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
