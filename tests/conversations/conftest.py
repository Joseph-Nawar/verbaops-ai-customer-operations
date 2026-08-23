"""Fixtures for the real PostgreSQL conversation persistence suite."""

from collections.abc import AsyncIterator
from os import environ

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from verbaops.conversations.service import ConversationService


@pytest.fixture(scope="session")
def database_url() -> str:
    url = environ.get("NOVACOMMERCE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("NOVACOMMERCE_TEST_DATABASE_URL is not configured")
    if not url.startswith("postgresql+asyncpg://"):
        pytest.fail("M3B persistence tests require postgresql+asyncpg")
    return url


@pytest_asyncio.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    database_engine = create_async_engine(database_url, pool_pre_ping=True, echo=False)
    yield database_engine
    await database_engine.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def service(session_factory: async_sessionmaker[AsyncSession]) -> ConversationService:
    return ConversationService(session_factory)


@pytest_asyncio.fixture
async def clean_verbaops_tables(engine: AsyncEngine) -> AsyncIterator[None]:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE TABLE tool_invocations, model_calls, agent_runs, messages, "
                "conversations RESTART IDENTITY CASCADE"
            )
        )
    yield
