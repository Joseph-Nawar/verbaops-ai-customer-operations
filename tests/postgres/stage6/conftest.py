"""PostgreSQL fixtures shared by Stage 6 action contract tests."""

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


@pytest_asyncio.fixture
async def clean_stage6_action_tables(postgres_engine: AsyncEngine) -> AsyncIterator[None]:
    async with postgres_engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE action_events, action_requests"))
    yield
