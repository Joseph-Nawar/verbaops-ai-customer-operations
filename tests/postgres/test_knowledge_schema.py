"""PostgreSQL knowledge schema contracts."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


@pytest.mark.postgres
@pytest.mark.contract
@pytest.mark.asyncio
async def test_knowledge_schema_contract_is_available(postgres_engine: AsyncEngine) -> None:
    async with postgres_engine.connect() as connection:
        tables = {
            row[0]
            for row in (
                await connection.execute(
                    text(
                        "select table_name from information_schema.tables "
                        "where table_schema='public' and table_name like 'knowledge_%'"
                    )
                )
            ).all()
        }
        assert tables == {
            "knowledge_documents",
            "knowledge_versions",
            "knowledge_chunks",
            "knowledge_ingestion_jobs",
        }
        vector_type = await connection.scalar(
            text(
                "select format_type(a.atttypid,a.atttypmod) from pg_attribute a "
                "where a.attrelid='knowledge_chunks'::regclass and a.attname='embedding'"
            )
        )
        assert vector_type == "vector(768)"
        indexes = {
            row[0]
            for row in (
                await connection.execute(
                    text(
                        "select indexname from pg_indexes "
                        "where tablename in ('knowledge_versions','knowledge_chunks')"
                    )
                )
            ).all()
        }
        assert "ix_knowledge_chunks_embedding_hnsw" in indexes
        assert "ix_knowledge_chunks_search_vector_gin" in indexes
        assert "uq_knowledge_versions_one_active" in indexes
