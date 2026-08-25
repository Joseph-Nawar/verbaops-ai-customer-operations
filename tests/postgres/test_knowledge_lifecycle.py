from collections.abc import Sequence
from datetime import date
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from verbaops.knowledge.embeddings import EMBEDDING_DIMENSION
from verbaops.knowledge.models import IngestionJobStatus, VersionStatus
from verbaops.knowledge.repository_tables import knowledge_chunks, knowledge_versions
from verbaops.knowledge.service import KnowledgeService
from verbaops.knowledge.validation import UploadMetadata

TENANT = UUID("60000000-0000-0000-0000-000000000001")


class DeterministicEmbedding:
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.25] * EMBEDDING_DIMENSION for _ in texts]


class FailingEmbedding:
    async def embed(self, _texts: Sequence[str]) -> list[list[float]]:
        raise RuntimeError("provider unavailable")


def metadata(version: str) -> UploadMetadata:
    return UploadMetadata(
        slug="lifecycle-policy",
        title="Lifecycle Policy",
        document_type="policy",
        language="en",
        version=version,
        effective_date=date(2026, 1, 1),
    )


@pytest.mark.postgres
@pytest.mark.contract
@pytest.mark.asyncio
async def test_version_switch_failure_preservation_and_idempotent_replay(
    postgres_engine: AsyncEngine,
) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    service = KnowledgeService(async_sessionmaker(postgres_engine, expire_on_commit=False))
    first = await service.queue_upload(TENANT, b"# Policy\nFirst active policy", metadata("v1"))
    assert (
        await service.process_job(first.ingestion_job_id, DeterministicEmbedding())
        is IngestionJobStatus.SUCCEEDED
    )
    assert (await service.activate(TENANT, first.version_id)).status is VersionStatus.ACTIVE

    second = await service.queue_upload(TENANT, b"# Policy\nSecond policy", metadata("v2"))
    first_job = await service.get_job(TENANT, first.ingestion_job_id)
    assert first_job is not None
    assert first_job.status is IngestionJobStatus.SUCCEEDED
    assert (
        await service.process_job(second.ingestion_job_id, FailingEmbedding())
        is IngestionJobStatus.FAILED
    )
    async with async_sessionmaker(postgres_engine, expire_on_commit=False)() as session:
        versions = (
            await session.execute(
                select(knowledge_versions.c.version, knowledge_versions.c.status).order_by(
                    knowledge_versions.c.version
                )
            )
        ).all()
    assert ("v1", VersionStatus.ACTIVE.value) in versions
    assert ("v2", VersionStatus.FAILED.value) in versions

    third = await service.queue_upload(TENANT, b"# Policy\nThird policy", metadata("v3"))
    assert (
        await service.process_job(third.ingestion_job_id, DeterministicEmbedding())
        is IngestionJobStatus.SUCCEEDED
    )
    await service.process_job(third.ingestion_job_id, DeterministicEmbedding())
    assert (await service.activate(TENANT, third.version_id)).status is VersionStatus.ACTIVE
    async with async_sessionmaker(postgres_engine, expire_on_commit=False)() as session:
        active = (
            (
                await session.execute(
                    select(knowledge_versions.c.version).where(
                        knowledge_versions.c.status == VersionStatus.ACTIVE.value
                    )
                )
            )
            .scalars()
            .all()
        )
        chunk_count = await session.scalar(
            select(func.count())
            .select_from(knowledge_chunks)
            .where(knowledge_chunks.c.version_id == third.version_id)
        )
    assert active == ["v3"]
    assert chunk_count == 1
