import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


@pytest_asyncio.fixture(autouse=True)
async def clean_knowledge_tables(postgres_engine: AsyncEngine) -> None:
    async with postgres_engine.begin() as connection:
        await connection.execute(text("DELETE FROM knowledge_ingestion_jobs"))
        await connection.execute(text("DELETE FROM knowledge_chunks"))
        await connection.execute(text("DELETE FROM knowledge_versions"))
        await connection.execute(text("DELETE FROM knowledge_documents"))
