"""Dedicated PostgreSQL fixtures for the Stage 5 contract."""

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


@pytest_asyncio.fixture
async def postgres_engine() -> AsyncIterator[AsyncEngine]:
    url = os.environ.get("VERBAOPS_DATABASE__URL")
    if not url:
        pytest.skip("VERBAOPS_DATABASE__URL is not configured")
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as error:
        await engine.dispose()
        pytest.skip(f"PostgreSQL unavailable: {type(error).__name__}")
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def clean_knowledge_tables(postgres_engine: AsyncEngine) -> AsyncIterator[None]:
    async with postgres_engine.begin() as connection:
        await connection.execute(text("DELETE FROM message_citations"))
        await connection.execute(text("DELETE FROM retrieval_candidates"))
        await connection.execute(text("DELETE FROM retrieval_invocations"))
        await connection.execute(text("DELETE FROM knowledge_ingestion_jobs"))
        await connection.execute(text("DELETE FROM knowledge_chunks"))
        await connection.execute(text("DELETE FROM knowledge_versions"))
        await connection.execute(text("DELETE FROM knowledge_documents"))
    yield
