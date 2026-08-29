from datetime import date
from uuid import UUID

import pytest
from sqlalchemy import func, insert
from sqlalchemy.ext.asyncio import AsyncEngine

from verbaops.knowledge.repository_tables import (
    knowledge_chunks,
    knowledge_documents,
    knowledge_versions,
)
from verbaops.retrieval.repository import RetrievalRepository

TENANT_A = UUID("60000000-0000-0000-0000-000000000001")
TENANT_B = UUID("60000000-0000-0000-0000-000000000002")
TENANT_C = UUID("60000000-0000-0000-0000-000000000003")
PROFILE = "multilingual-e5-base-v1"


def uid(number: int) -> UUID:
    return UUID(int=number)


async def seed_retrieval_rows(postgres_engine: AsyncEngine) -> dict[str, UUID]:
    rows = {
        "active": (TENANT_A, "active", date(2026, 1, 1), PROFILE),
        "incompatible": (TENANT_A, "active", date(2026, 1, 1), "legacy-profile"),
        "ready": (TENANT_A, "ready", date(2026, 1, 1), PROFILE),
        "superseded": (TENANT_A, "superseded", date(2026, 1, 1), PROFILE),
        "failed": (TENANT_A, "failed", date(2026, 1, 1), PROFILE),
        "quarantined": (TENANT_A, "quarantined", date(2026, 1, 1), PROFILE),
        "future": (TENANT_A, "active", date(2099, 1, 1), PROFILE),
        "other_tenant": (TENANT_B, "active", date(2026, 1, 1), PROFILE),
    }
    async with postgres_engine.begin() as connection:
        for index, (name, (tenant, status, effective_date, profile)) in enumerate(rows.items(), 1):
            document_id = uid(index * 10)
            version_id = uid(index * 10 + 1)
            chunk_id = uid(index * 10 + 2)
            await connection.execute(
                insert(knowledge_documents).values(
                    id=document_id,
                    tenant_id=tenant,
                    slug=f"{name}-policy",
                    title=f"{name.title()} Policy",
                    document_type="policy",
                    language="en",
                )
            )
            await connection.execute(
                insert(knowledge_versions).values(
                    id=version_id,
                    document_id=document_id,
                    version="2026.1",
                    effective_date=effective_date,
                    status=status,
                    source_content="# Returns\nReturn window is 30 days.",
                    source_hash="a" * 64,
                    embedding_profile=profile,
                    embedding_model="intfloat/multilingual-e5-base",
                )
            )
            vector = [0.0] * 768
            vector[0 if name == "active" else 1] = 1.0
            await connection.execute(
                insert(knowledge_chunks).values(
                    id=chunk_id,
                    version_id=version_id,
                    tenant_id=tenant,
                    document_id=document_id,
                    document_version="2026.1",
                    section="Return Window",
                    language="en",
                    effective_date=effective_date,
                    chunk_index=0,
                    content="Return window is 30 days.",
                    content_hash=(f"{index:064d}")[-64:],
                    embedding=vector,
                    search_vector=func.to_tsvector("english", "Return window is 30 days."),
                )
            )
    return {name: uid(index * 10 + 2) for index, name in enumerate(rows, 1)}


@pytest.mark.postgres
@pytest.mark.contract
@pytest.mark.asyncio
async def test_dense_and_lexical_retrieval_apply_all_scope_and_version_filters(
    postgres_engine: AsyncEngine,
) -> None:
    expected = await seed_retrieval_rows(postgres_engine)
    repository = RetrievalRepository()
    vector = [1.0] + [0.0] * 767

    async with postgres_engine.connect() as connection:
        dense = await repository.search_dense(
            connection,
            tenant_id=TENANT_A,
            vector=vector,
            embedding_profile=PROFILE,
            language="en",
        )
        lexical = await repository.search_lexical(
            connection,
            tenant_id=TENANT_A,
            query="return window 30 days",
            language="en",
        )

    assert [item.chunk.chunk_id for item in dense] == [expected["active"]]
    assert [item.chunk.chunk_id for item in lexical] == [
        expected["active"],
        expected["incompatible"],
    ]

    async with postgres_engine.connect() as connection:
        assert (
            await repository.search_dense(
                connection,
                tenant_id=TENANT_C,
                vector=[0.0, 1.0] + [0.0] * 766,
                embedding_profile=PROFILE,
                language="en",
            )
            == []
        )
        assert await repository.search_lexical(
            connection,
            tenant_id=TENANT_B,
            query="return window 30 days",
            language="en",
        )


@pytest.mark.postgres
@pytest.mark.contract
@pytest.mark.asyncio
async def test_retrieval_rejects_inconsistent_document_and_chunk_tenants(
    postgres_engine: AsyncEngine,
) -> None:
    document_id = uid(901)
    version_id = uid(902)
    chunk_id = uid(903)
    async with postgres_engine.begin() as connection:
        await connection.execute(
            insert(knowledge_documents).values(
                id=document_id,
                tenant_id=TENANT_B,
                slug="inconsistent-policy",
                title="Inconsistent Policy",
                document_type="policy",
                language="en",
            )
        )
        await connection.execute(
            insert(knowledge_versions).values(
                id=version_id,
                document_id=document_id,
                version="2026.1",
                effective_date=date(2026, 1, 1),
                status="active",
                source_content="# Returns\nReturn window is 30 days.",
                source_hash="b" * 64,
                embedding_profile=PROFILE,
                embedding_model="intfloat/multilingual-e5-base",
            )
        )
        await connection.execute(
            insert(knowledge_chunks).values(
                id=chunk_id,
                version_id=version_id,
                tenant_id=TENANT_A,
                document_id=document_id,
                document_version="2026.1",
                section="Return Window",
                language="en",
                effective_date=date(2026, 1, 1),
                chunk_index=0,
                content="Return window is 30 days.",
                content_hash="c" * 64,
                embedding=[1.0] + [0.0] * 767,
                search_vector=func.to_tsvector("english", "Return window is 30 days."),
            )
        )

    repository = RetrievalRepository()
    async with postgres_engine.connect() as connection:
        dense = await repository.search_dense(
            connection,
            tenant_id=TENANT_A,
            vector=[1.0] + [0.0] * 767,
            embedding_profile=PROFILE,
            language="en",
        )
        lexical = await repository.search_lexical(
            connection,
            tenant_id=TENANT_A,
            query="return window 30 days",
            language="en",
        )

    assert all(item.chunk.chunk_id != chunk_id for item in dense)
    assert all(item.chunk.chunk_id != chunk_id for item in lexical)
