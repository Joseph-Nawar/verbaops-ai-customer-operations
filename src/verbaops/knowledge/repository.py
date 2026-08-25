"""Tenant-scoped PostgreSQL repository for knowledge lifecycle state."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from verbaops.knowledge.chunking import ChunkDraft, content_hash
from verbaops.knowledge.models import (
    DuplicateVersionError,
    IngestionIdentifiers,
    IngestionJobStatus,
    JobView,
    VersionMetadata,
    VersionStatus,
)
from verbaops.knowledge.repository_tables import (
    knowledge_chunks,
    knowledge_documents,
    knowledge_ingestion_jobs,
    knowledge_versions,
)
from verbaops.knowledge.validation import UploadMetadata


@dataclass(frozen=True, slots=True)
class ProcessingBundle:
    job_status: IngestionJobStatus
    source_content: str
    version_id: UUID
    document_id: UUID
    tenant_id: UUID
    document_version: str
    language: str
    effective_date: Any


@dataclass(frozen=True, slots=True)
class ProcessingClaim:
    bundle: ProcessingBundle
    claimed: bool


class KnowledgeRepository:
    """SQL statements for the four M5A tables; all lookups are tenant-safe."""

    async def create_document_version_job(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        metadata: UploadMetadata,
        normalized_source: str,
        source_hash: str,
        quarantined: bool,
    ) -> IngestionIdentifiers:
        document = (
            (
                await session.execute(
                    sa.select(knowledge_documents).where(
                        knowledge_documents.c.tenant_id == tenant_id,
                        knowledge_documents.c.slug == metadata.slug,
                        knowledge_documents.c.language == metadata.language,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if document is None:
            document_id = uuid4()
            await session.execute(
                knowledge_documents.insert().values(
                    id=document_id,
                    tenant_id=tenant_id,
                    slug=metadata.slug,
                    title=metadata.title,
                    document_type=metadata.document_type,
                    language=metadata.language,
                    created_at=datetime.now(UTC),
                )
            )
        else:
            document_id = document["id"]
        existing = (
            (
                await session.execute(
                    sa.select(knowledge_versions).where(
                        knowledge_versions.c.document_id == document_id,
                        knowledge_versions.c.version == metadata.version,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if existing is not None:
            if existing["source_hash"].strip() != source_hash:
                raise DuplicateVersionError("version_source_conflict")
            job = (
                (
                    await session.execute(
                        sa.select(knowledge_ingestion_jobs).where(
                            knowledge_ingestion_jobs.c.version_id == existing["id"]
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if job is None:
                job_id = uuid4()
                status = (
                    IngestionJobStatus.QUARANTINED if quarantined else IngestionJobStatus.QUEUED
                )
                await session.execute(
                    knowledge_ingestion_jobs.insert().values(
                        id=job_id,
                        tenant_id=tenant_id,
                        version_id=existing["id"],
                        status=status.value,
                        attempt_count=0,
                        created_at=datetime.now(UTC),
                    )
                )
            else:
                job_id = job["id"]
                status = IngestionJobStatus(job["status"])
            return IngestionIdentifiers(document_id, existing["id"], job_id, status)

        version_id = uuid4()
        job_id = uuid4()
        version_status = VersionStatus.QUARANTINED if quarantined else VersionStatus.PROCESSING
        job_status = IngestionJobStatus.QUARANTINED if quarantined else IngestionJobStatus.QUEUED
        await session.execute(
            knowledge_versions.insert().values(
                id=version_id,
                document_id=document_id,
                version=metadata.version,
                effective_date=metadata.effective_date,
                status=version_status.value,
                source_content=normalized_source,
                source_hash=source_hash,
                created_at=datetime.now(UTC),
            )
        )
        await session.execute(
            knowledge_ingestion_jobs.insert().values(
                id=job_id,
                tenant_id=tenant_id,
                version_id=version_id,
                status=job_status.value,
                attempt_count=0,
                created_at=datetime.now(UTC),
            )
        )
        return IngestionIdentifiers(document_id, version_id, job_id, job_status)

    async def load_job_for_processing(
        self, session: AsyncSession, job_id: UUID
    ) -> ProcessingBundle | None:
        row = (
            (
                await session.execute(
                    sa.select(
                        knowledge_ingestion_jobs.c.status.label("job_status"),
                        knowledge_versions.c.source_content,
                        knowledge_versions.c.id.label("version_id"),
                        knowledge_versions.c.document_id,
                        knowledge_ingestion_jobs.c.tenant_id,
                        knowledge_versions.c.version,
                        knowledge_documents.c.language,
                        knowledge_versions.c.effective_date,
                    )
                    .join(
                        knowledge_versions,
                        knowledge_versions.c.id == knowledge_ingestion_jobs.c.version_id,
                    )
                    .join(
                        knowledge_documents,
                        knowledge_documents.c.id == knowledge_versions.c.document_id,
                    )
                    .where(knowledge_ingestion_jobs.c.id == job_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return ProcessingBundle(
            job_status=IngestionJobStatus(row["job_status"]),
            source_content=row["source_content"],
            version_id=row["version_id"],
            document_id=row["document_id"],
            tenant_id=row["tenant_id"],
            document_version=row["version"],
            language=row["language"],
            effective_date=row["effective_date"],
        )

    async def mark_processing(self, session: AsyncSession, job_id: UUID) -> ProcessingClaim | None:
        """Atomically claim a queued job before external embedding work."""

        result = await session.execute(
            knowledge_ingestion_jobs.update()
            .where(
                knowledge_ingestion_jobs.c.id == job_id,
                knowledge_ingestion_jobs.c.status == IngestionJobStatus.QUEUED.value,
            )
            .values(
                status=IngestionJobStatus.PROCESSING.value,
                attempt_count=knowledge_ingestion_jobs.c.attempt_count + 1,
                started_at=datetime.now(UTC),
            )
            .returning(knowledge_ingestion_jobs.c.id)
        )
        claimed = result.first() is not None
        bundle = await self.load_job_for_processing(session, job_id)
        if bundle is None:
            return None
        return ProcessingClaim(bundle=bundle, claimed=claimed)

    async def load_job_for_tenant(
        self, session: AsyncSession, tenant_id: UUID, job_id: UUID
    ) -> JobView | None:
        row = (
            (
                await session.execute(
                    sa.select(
                        knowledge_ingestion_jobs.c.id,
                        knowledge_ingestion_jobs.c.version_id,
                        knowledge_ingestion_jobs.c.status,
                        knowledge_ingestion_jobs.c.attempt_count,
                        knowledge_ingestion_jobs.c.failure_code,
                        knowledge_ingestion_jobs.c.created_at,
                        knowledge_ingestion_jobs.c.started_at,
                        knowledge_ingestion_jobs.c.completed_at,
                    ).where(
                        knowledge_ingestion_jobs.c.id == job_id,
                        knowledge_ingestion_jobs.c.tenant_id == tenant_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return JobView(
            id=row["id"],
            version_id=row["version_id"],
            status=IngestionJobStatus(row["status"]),
            attempt_count=row["attempt_count"],
            failure_code=row["failure_code"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
        )

    async def set_task_id(self, session: AsyncSession, job_id: UUID, task_id: str) -> None:
        await session.execute(
            knowledge_ingestion_jobs.update()
            .where(knowledge_ingestion_jobs.c.id == job_id)
            .values(celery_task_id=task_id)
        )

    async def store_ready_chunks(
        self,
        session: AsyncSession,
        *,
        job_id: UUID,
        drafts: Sequence[ChunkDraft],
        vectors: Sequence[Sequence[float]],
    ) -> IngestionJobStatus | None:
        state = (
            (
                await session.execute(
                    sa.select(
                        knowledge_ingestion_jobs.c.status,
                        knowledge_ingestion_jobs.c.version_id,
                    )
                    .where(knowledge_ingestion_jobs.c.id == job_id)
                    .with_for_update()
                )
            )
            .mappings()
            .one_or_none()
        )
        if state is None:
            return None
        job_status = IngestionJobStatus(state["status"])
        if job_status is not IngestionJobStatus.PROCESSING:
            return job_status
        bundle = await self.load_job_for_processing(session, job_id)
        if bundle is None:
            return None
        if len(drafts) != len(vectors):
            raise ValueError("embedding_partial_batch")
        await session.execute(
            knowledge_chunks.delete().where(knowledge_chunks.c.version_id == bundle.version_id)
        )
        now = datetime.now(UTC)
        values = [
            {
                "id": uuid4(),
                "version_id": bundle.version_id,
                "tenant_id": bundle.tenant_id,
                "document_id": bundle.document_id,
                "document_version": bundle.document_version,
                "section": draft.section,
                "language": bundle.language,
                "effective_date": bundle.effective_date,
                "chunk_index": draft.chunk_index,
                "content": draft.content,
                "content_hash": content_hash(draft.content),
                "embedding": list(vector),
                "search_vector": sa.func.to_tsvector("english", draft.content),
                "created_at": now,
            }
            for draft, vector in zip(drafts, vectors, strict=True)
        ]
        if values:
            await session.execute(knowledge_chunks.insert().values(values))
        await session.execute(
            knowledge_versions.update()
            .where(
                knowledge_versions.c.id == bundle.version_id,
                knowledge_versions.c.status == VersionStatus.PROCESSING.value,
            )
            .values(status=VersionStatus.READY.value, failure_code=None)
        )
        await session.execute(
            knowledge_ingestion_jobs.update()
            .where(
                knowledge_ingestion_jobs.c.id == job_id,
                knowledge_ingestion_jobs.c.status == IngestionJobStatus.PROCESSING.value,
            )
            .values(
                status=IngestionJobStatus.SUCCEEDED.value,
                completed_at=now,
                failure_code=None,
            )
        )
        return IngestionJobStatus.SUCCEEDED

    async def mark_failed(
        self, session: AsyncSession, job_id: UUID, code: str
    ) -> IngestionJobStatus | None:
        row = (
            (
                await session.execute(
                    sa.select(
                        knowledge_ingestion_jobs.c.status,
                        knowledge_ingestion_jobs.c.version_id,
                    )
                    .where(knowledge_ingestion_jobs.c.id == job_id)
                    .with_for_update()
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        job_status = IngestionJobStatus(row["status"])
        if job_status is not IngestionJobStatus.PROCESSING:
            return job_status
        now = datetime.now(UTC)
        await session.execute(
            knowledge_chunks.delete().where(knowledge_chunks.c.version_id == row["version_id"])
        )
        await session.execute(
            knowledge_versions.update()
            .where(
                knowledge_versions.c.id == row["version_id"],
                knowledge_versions.c.status == VersionStatus.PROCESSING.value,
            )
            .values(status=VersionStatus.FAILED.value, failure_code=code)
        )
        await session.execute(
            knowledge_ingestion_jobs.update()
            .where(
                knowledge_ingestion_jobs.c.id == job_id,
                knowledge_ingestion_jobs.c.status == IngestionJobStatus.PROCESSING.value,
            )
            .values(status=IngestionJobStatus.FAILED.value, failure_code=code, completed_at=now)
        )
        return IngestionJobStatus.FAILED

    async def load_version_for_tenant(
        self, session: AsyncSession, *, tenant_id: UUID, version_id: UUID
    ) -> VersionMetadata | None:
        row = (
            (
                await session.execute(
                    sa.select(
                        knowledge_versions.c.id,
                        knowledge_versions.c.document_id,
                        knowledge_documents.c.slug,
                        knowledge_documents.c.title,
                        knowledge_documents.c.document_type,
                        knowledge_documents.c.language,
                        knowledge_versions.c.version,
                        knowledge_versions.c.effective_date,
                        knowledge_versions.c.status,
                        knowledge_versions.c.activated_at,
                    )
                    .join(
                        knowledge_documents,
                        knowledge_documents.c.id == knowledge_versions.c.document_id,
                    )
                    .where(
                        knowledge_versions.c.id == version_id,
                        knowledge_documents.c.tenant_id == tenant_id,
                    )
                    .with_for_update()
                )
            )
            .mappings()
            .one_or_none()
        )
        return _version_metadata(row) if row is not None else None

    async def activate_version(
        self, session: AsyncSession, *, tenant_id: UUID, version_id: UUID
    ) -> VersionMetadata:
        version = await self.load_version_for_tenant(
            session, tenant_id=tenant_id, version_id=version_id
        )
        if version is None:
            raise LookupError("version_not_found")
        await session.execute(
            knowledge_versions.update()
            .where(
                knowledge_versions.c.document_id == version.document_id,
                knowledge_versions.c.status == VersionStatus.ACTIVE.value,
            )
            .values(status=VersionStatus.SUPERSEDED.value)
        )
        now = datetime.now(UTC)
        await session.execute(
            knowledge_versions.update()
            .where(knowledge_versions.c.id == version_id)
            .values(status=VersionStatus.ACTIVE.value, activated_at=now)
        )
        return VersionMetadata(
            id=version.id,
            document_id=version.document_id,
            slug=version.slug,
            title=version.title,
            document_type=version.document_type,
            language=version.language,
            version=version.version,
            effective_date=version.effective_date,
            status=VersionStatus.ACTIVE,
            activated_at=now,
        )


def _version_metadata(row: Any) -> VersionMetadata:
    return VersionMetadata(
        id=row["id"],
        document_id=row["document_id"],
        slug=row["slug"],
        title=row["title"],
        document_type=row["document_type"],
        language=row["language"],
        version=row["version"],
        effective_date=row["effective_date"],
        status=VersionStatus(row["status"]),
        activated_at=row["activated_at"],
    )
