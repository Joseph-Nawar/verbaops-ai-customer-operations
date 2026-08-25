"""Thin Celery transport wrapper for ordinary knowledge service behavior."""

from __future__ import annotations

import asyncio
from uuid import UUID

import httpx

from verbaops.config.settings import Settings
from verbaops.db.resources import create_database_resources, dispose_database_resources
from verbaops.knowledge.embeddings import EmbeddingClient
from verbaops.knowledge.service import KnowledgeService
from verbaops.worker.celery_app import celery_app


@celery_app.task(name="verbaops.knowledge.ingest")  # type: ignore[untyped-decorator]
def ingest_knowledge_job(ingestion_job_id: str) -> str:
    """Transport one job identifier to the application-owned ingestion service."""

    asyncio.run(_run_knowledge_job(UUID(ingestion_job_id)))
    return ingestion_job_id


def enqueue_knowledge_job(ingestion_job_id: UUID) -> str:
    """Publish a job identifier and return the broker task identity."""

    return str(ingest_knowledge_job.delay(str(ingestion_job_id)).id)


async def _run_knowledge_job(ingestion_job_id: UUID) -> None:
    settings = Settings()
    database = create_database_resources(settings)
    http_client = httpx.AsyncClient()
    try:
        embedding_client = EmbeddingClient(settings.llm, http_client)
        service = KnowledgeService(database.session_factory)
        await service.process_job(ingestion_job_id, embedding_client)
    finally:
        await http_client.aclose()
        await dispose_database_resources(database)
