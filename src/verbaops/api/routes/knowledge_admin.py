"""Tenant-admin routes for versioned knowledge ingestion."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from verbaops.api.dependencies import get_knowledge_service, get_trusted_context
from verbaops.api.errors import PublicAPIError
from verbaops.auth.context import Role, TrustedContext
from verbaops.knowledge.models import (
    DuplicateVersionError,
    IngestionJobStatus,
    JobView,
    VersionMetadata,
)
from verbaops.knowledge.service import (
    KnowledgeNotFoundError,
    KnowledgeService,
)
from verbaops.knowledge.tasks import enqueue_knowledge_job
from verbaops.knowledge.validation import MAX_SOURCE_BYTES, UploadMetadata, UploadValidationError

router = APIRouter(prefix="/v1/admin/knowledge", tags=["knowledge-admin"])
ContextDependency = Annotated[TrustedContext, Depends(get_trusted_context)]
ServiceDependency = Annotated[KnowledgeService, Depends(get_knowledge_service)]


class IngestionAcceptedResponse(BaseModel):
    document_id: UUID
    version_id: UUID
    ingestion_job_id: UUID
    status: Literal["queued", "quarantined"]


class IngestionStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ingestion_job_id: UUID
    version_id: UUID
    status: IngestionJobStatus
    attempt_count: int = Field(ge=0)
    failure_code: str | None
    created_at: str
    started_at: str | None
    completed_at: str | None


class ActivatedVersionResponse(BaseModel):
    id: UUID
    document_id: UUID
    slug: str
    title: str
    document_type: str
    language: str
    version: str
    effective_date: date
    status: Literal["active"]
    activated_at: str | None


def _require_admin(context: TrustedContext) -> None:
    if Role.TENANT_ADMIN not in context.roles:
        raise PublicAPIError(403, "authorization_failed", "authorization failed")


@router.post("/documents", response_model=IngestionAcceptedResponse, status_code=202)
async def upload_document(
    file: Annotated[UploadFile, File(...)],
    slug: Annotated[str, Form(...)],
    title: Annotated[str, Form(...)],
    document_type: Annotated[str, Form(...)],
    language: Annotated[str, Form(...)],
    version: Annotated[str, Form(...)],
    effective_date: Annotated[date, Form(...)],
    context: ContextDependency,
    service: ServiceDependency,
) -> IngestionAcceptedResponse:
    _require_admin(context)
    try:
        source = await file.read(MAX_SOURCE_BYTES + 1)
        identifiers = await service.queue_upload(
            context.tenant_id,
            source,
            UploadMetadata(
                slug=slug,
                title=title,
                document_type=document_type,
                language=language,
                version=version,
                effective_date=effective_date,
                filename=file.filename or "document.md",
            ),
        )
    except UploadValidationError as error:
        raise PublicAPIError(422, error.code, "knowledge upload validation failed") from None
    except DuplicateVersionError:
        raise PublicAPIError(409, "version_conflict", "knowledge version already exists") from None
    if identifiers.status is IngestionJobStatus.QUEUED:
        task_id = enqueue_knowledge_job(identifiers.ingestion_job_id)
        await service.attach_task_id(context.tenant_id, identifiers.ingestion_job_id, task_id)
    return IngestionAcceptedResponse(
        document_id=identifiers.document_id,
        version_id=identifiers.version_id,
        ingestion_job_id=identifiers.ingestion_job_id,
        status=identifiers.status.value,  # type: ignore[arg-type]
    )


@router.get("/ingestions/{ingestion_job_id}", response_model=IngestionStatusResponse)
async def get_ingestion_status(
    ingestion_job_id: UUID,
    context: ContextDependency,
    service: ServiceDependency,
) -> IngestionStatusResponse:
    _require_admin(context)
    job = await service.get_job(context.tenant_id, ingestion_job_id)
    if job is None:
        raise PublicAPIError(404, "knowledge_not_found", "knowledge ingestion not found")
    return _job_response(job)


@router.post(
    "/versions/{version_id}/activate",
    response_model=ActivatedVersionResponse,
)
async def activate_version(
    version_id: UUID,
    context: ContextDependency,
    service: ServiceDependency,
) -> ActivatedVersionResponse:
    _require_admin(context)
    try:
        version = await service.activate(context.tenant_id, version_id)
    except KnowledgeNotFoundError:
        raise PublicAPIError(404, "knowledge_not_found", "knowledge version not found") from None
    except ValueError as error:
        code = str(error)
        status = 422 if code == "future_effective_date" else 409
        raise PublicAPIError(status, code, "knowledge version cannot be activated") from None
    return _version_response(version)


def _job_response(job: JobView) -> IngestionStatusResponse:
    return IngestionStatusResponse(
        ingestion_job_id=job.id,
        version_id=job.version_id,
        status=job.status,
        attempt_count=job.attempt_count,
        failure_code=job.failure_code,
        created_at=job.created_at.isoformat(),
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
    )


def _version_response(version: VersionMetadata) -> ActivatedVersionResponse:
    return ActivatedVersionResponse(
        id=version.id,
        document_id=version.document_id,
        slug=version.slug,
        title=version.title,
        document_type=version.document_type,
        language=version.language,
        version=version.version,
        effective_date=version.effective_date,
        status="active",
        activated_at=version.activated_at.isoformat() if version.activated_at else None,
    )
