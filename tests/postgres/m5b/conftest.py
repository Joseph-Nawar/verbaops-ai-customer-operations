import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def _clear_m5b_tables(postgres_engine: AsyncEngine) -> None:
    async with postgres_engine.begin() as connection:
        await connection.execute(text("DELETE FROM message_citations"))
        await connection.execute(text("DELETE FROM retrieval_candidates"))
        await connection.execute(text("DELETE FROM retrieval_invocations"))
        await connection.execute(text("DELETE FROM knowledge_ingestion_jobs"))
        await connection.execute(text("DELETE FROM knowledge_chunks"))
        await connection.execute(text("DELETE FROM knowledge_versions"))
        await connection.execute(text("DELETE FROM knowledge_documents"))


@pytest_asyncio.fixture(autouse=True)
async def clear_m5b_tables(postgres_engine: AsyncEngine) -> None:
    await _clear_m5b_tables(postgres_engine)
