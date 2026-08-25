"""Knowledge validation, ingestion, and version activation services."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from verbaops.knowledge.chunking import chunk_sections, source_hash
from verbaops.knowledge.models import (
    IngestionIdentifiers,
    IngestionJobStatus,
    JobView,
    VersionMetadata,
    VersionStatus,
)
from verbaops.knowledge.parsing import detect_sections
from verbaops.knowledge.repository import KnowledgeRepository
from verbaops.knowledge.validation import UploadMetadata, validate_upload


def ensure_activation_allowed(status: VersionStatus, effective_date: date, *, today: date) -> None:
    """Enforce M5A's explicit, immediate activation rules."""

    if status is not VersionStatus.READY:
        raise ValueError("version_not_ready")
    if effective_date > today:
        raise ValueError("future_effective_date")


class KnowledgeNotFoundError(LookupError):
    """A tenant-scoped knowledge identifier was not found."""


class KnowledgeIngestionError(RuntimeError):
    """A safe ingestion failure code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class EmbeddingProvider(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class KnowledgeService:
    """Coordinate ordinary testable knowledge operations around a repository."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        repository: KnowledgeRepository | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.repository = repository or KnowledgeRepository()

    async def queue_upload(
        self,
        tenant_id: UUID,
        source: bytes,
        metadata: UploadMetadata,
    ) -> IngestionIdentifiers:
        upload = validate_upload(source, metadata)
        async with self.session_factory() as session, session.begin():
            source_digest = source_hash(upload.normalized_source)
            return await self.repository.create_document_version_job(
                session,
                tenant_id=tenant_id,
                metadata=upload.metadata,
                normalized_source=upload.normalized_source,
                source_hash=source_digest,
                quarantined=upload.quarantine,
            )

    async def process_job(
        self,
        job_id: UUID,
        embedding_client: EmbeddingProvider,
    ) -> IngestionJobStatus:
        async with self.session_factory() as session:
            async with session.begin():
                bundle = await self.repository.load_job_for_processing(session, job_id)
                if bundle is None:
                    raise KnowledgeNotFoundError()
                if bundle.job_status in {
                    IngestionJobStatus.SUCCEEDED,
                    IngestionJobStatus.QUARANTINED,
                }:
                    return bundle.job_status
                await self.repository.mark_processing(session, job_id)

            try:
                sections = detect_sections(bundle.source_content)
                drafts = chunk_sections(sections)
                vectors = await embedding_client.embed([draft.content for draft in drafts])
                if len(vectors) != len(drafts):
                    raise KnowledgeIngestionError("embedding_partial_batch")
            except KnowledgeIngestionError as error:
                await self._fail(job_id, error.code)
                return IngestionJobStatus.FAILED
            except Exception:
                await self._fail(job_id, "embedding_failed")
                return IngestionJobStatus.FAILED

            try:
                async with session.begin():
                    await self.repository.store_ready_chunks(
                        session,
                        job_id=job_id,
                        drafts=drafts,
                        vectors=vectors,
                    )
            except Exception:
                await self._fail(job_id, "storage_failed")
                return IngestionJobStatus.FAILED
            return IngestionJobStatus.SUCCEEDED

    async def activate(
        self,
        tenant_id: UUID,
        version_id: UUID,
        *,
        today: date | None = None,
    ) -> VersionMetadata:
        async with self.session_factory() as session, session.begin():
            version = await self.repository.load_version_for_tenant(
                session, tenant_id=tenant_id, version_id=version_id
            )
            if version is None:
                raise KnowledgeNotFoundError()
            if version.status is VersionStatus.ACTIVE:
                return version
            ensure_activation_allowed(
                version.status,
                version.effective_date,
                today=today or datetime.now(UTC).date(),
            )
            return await self.repository.activate_version(
                session,
                tenant_id=tenant_id,
                version_id=version_id,
            )

    async def get_job(self, tenant_id: UUID, job_id: UUID) -> JobView | None:
        async with self.session_factory() as session:
            return await self.repository.load_job_for_tenant(session, tenant_id, job_id)

    async def attach_task_id(self, tenant_id: UUID, job_id: UUID, task_id: str) -> None:
        async with self.session_factory() as session, session.begin():
            job = await self.repository.load_job_for_tenant(session, tenant_id, job_id)
            if job is not None:
                await self.repository.set_task_id(session, job_id, task_id)

    async def _fail(self, job_id: UUID, code: str) -> None:
        async with self.session_factory() as session, session.begin():
            await self.repository.mark_failed(session, job_id, code)


def make_uuid() -> UUID:
    """Small seam for deterministic repository tests."""

    return uuid4()
