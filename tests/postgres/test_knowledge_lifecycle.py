import asyncio
from collections.abc import Sequence
from datetime import date
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from verbaops.knowledge.embeddings import EMBEDDING_DIMENSION
from verbaops.knowledge.models import IngestionJobStatus, VersionStatus
from verbaops.knowledge.repository_tables import (
    knowledge_chunks,
    knowledge_ingestion_jobs,
    knowledge_versions,
)
from verbaops.knowledge.service import KnowledgeService
from verbaops.knowledge.validation import UploadMetadata

TENANT = UUID("60000000-0000-0000-0000-000000000001")


class DeterministicEmbedding:
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.25] * EMBEDDING_DIMENSION for _ in texts]


class FailingEmbedding:
    async def embed(self, _texts: Sequence[str]) -> list[list[float]]:
        raise RuntimeError("provider unavailable")


class BlockingEmbedding:
    def __init__(self) -> None:
        self.calls = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += 1
        self.entered.set()
        await self.release.wait()
        return [[0.25] * EMBEDDING_DIMENSION for _ in texts]


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


@pytest.mark.postgres
@pytest.mark.contract
@pytest.mark.asyncio
async def test_concurrent_duplicate_delivery_has_one_claim_and_defends_success_from_stale_failure(
    postgres_engine: AsyncEngine,
) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    service = KnowledgeService(async_sessionmaker(postgres_engine, expire_on_commit=False))
    queued = await service.queue_upload(
        TENANT,
        b"# Policy\nPrimary policy text.\n## Details\nAdditional policy details.",
        metadata("concurrent-v1"),
    )
    embedding = BlockingEmbedding()
    barrier = asyncio.Barrier(2)

    async def deliver_duplicate() -> IngestionJobStatus:
        await barrier.wait()
        return await service.process_job(queued.ingestion_job_id, embedding)

    first = asyncio.create_task(deliver_duplicate())
    second = asyncio.create_task(deliver_duplicate())
    await asyncio.wait_for(embedding.entered.wait(), timeout=2)
    await asyncio.sleep(0)
    assert not first.done() or not second.done()
    embedding.release.set()
    statuses = await asyncio.wait_for(asyncio.gather(first, second), timeout=2)

    assert embedding.calls == 1
    assert IngestionJobStatus.SUCCEEDED in statuses
    assert IngestionJobStatus.PROCESSING in statuses
    job = await service.get_job(TENANT, queued.ingestion_job_id)
    assert job is not None
    assert job.status is IngestionJobStatus.SUCCEEDED
    assert job.attempt_count == 1

    async with async_sessionmaker(postgres_engine, expire_on_commit=False)() as session:
        version_status = await session.scalar(
            select(knowledge_versions.c.status).where(knowledge_versions.c.id == queued.version_id)
        )
        chunk_indexes = (
            (
                await session.execute(
                    select(knowledge_chunks.c.chunk_index).where(
                        knowledge_chunks.c.version_id == queued.version_id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert version_status == VersionStatus.READY.value
    assert len(chunk_indexes) == 2
    assert len(set(chunk_indexes)) == 2

    await service._fail(queued.ingestion_job_id, "stale_worker_failure")
    job_after_stale_failure = await service.get_job(TENANT, queued.ingestion_job_id)
    assert job_after_stale_failure is not None
    assert job_after_stale_failure.status is IngestionJobStatus.SUCCEEDED
    async with async_sessionmaker(postgres_engine, expire_on_commit=False)() as session:
        version_after_stale_failure = await session.scalar(
            select(knowledge_versions.c.status).where(knowledge_versions.c.id == queued.version_id)
        )
        remaining_chunks = await session.scalar(
            select(func.count())
            .select_from(knowledge_chunks)
            .where(knowledge_chunks.c.version_id == queued.version_id)
        )
        processing_claims = await session.scalar(
            select(knowledge_ingestion_jobs.c.attempt_count).where(
                knowledge_ingestion_jobs.c.id == queued.ingestion_job_id
            )
        )
    assert version_after_stale_failure == VersionStatus.READY.value
    assert remaining_chunks == 2
    assert processing_claims == 1
