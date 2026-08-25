"""Domain values for versioned knowledge ingestion."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID


class VersionStatus(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    FAILED = "failed"
    QUARANTINED = "quarantined"


class IngestionJobStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    QUARANTINED = "quarantined"


class DuplicateVersionError(ValueError):
    """A version already exists with different source content."""


@dataclass(frozen=True, slots=True)
class IngestionIdentifiers:
    document_id: UUID
    version_id: UUID
    ingestion_job_id: UUID
    status: IngestionJobStatus


@dataclass(frozen=True, slots=True)
class IngestionJobRecord:
    id: UUID
    tenant_id: UUID
    version_id: UUID
    status: IngestionJobStatus
    attempt_count: int
    failure_code: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class JobView:
    id: UUID
    version_id: UUID
    status: IngestionJobStatus
    attempt_count: int
    failure_code: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class VersionMetadata:
    id: UUID
    document_id: UUID
    slug: str
    title: str
    document_type: str
    language: str
    version: str
    effective_date: date
    status: VersionStatus
    activated_at: datetime | None
