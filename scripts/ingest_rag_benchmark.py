"""Ingest the committed NovaCommerce corpus through the real M5A path.

This helper intentionally requires a live embedding gateway. It never writes
synthetic vectors and processes historical versions before current versions so
the final lifecycle is deterministic.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import date
from pathlib import Path
from uuid import UUID

import httpx
import sqlalchemy as sa
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from verbaops.config.settings import LLMSettings
from verbaops.knowledge.embeddings import EmbeddingClient
from verbaops.knowledge.repository_tables import (
    knowledge_chunks,
    knowledge_documents,
    knowledge_versions,
)
from verbaops.knowledge.service import KnowledgeService
from verbaops.knowledge.validation import UploadMetadata


async def ingest(
    root: Path, database_url: str, tenant_id: UUID, gateway_url: str
) -> dict[str, int]:
    engine = create_async_engine(database_url, pool_pre_ping=True, echo=False)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    service = KnowledgeService(sessions)
    manifest = json.loads(
        (root / "knowledge/novacommerce/manifest.json").read_text(encoding="utf-8")
    )
    entries = sorted(
        manifest["documents"],
        key=lambda entry: (entry["intent"] != "historical", entry["slug"], entry["version"]),
    )
    async with httpx.AsyncClient() as client:
        settings = LLMSettings(
            base_url=gateway_url,
            api_key=SecretStr(os.environ.get("VERBAOPS_LLM__API_KEY", "benchmark-local-key")),
        )
        embedding = EmbeddingClient(settings, client)
        for entry in entries:
            source_path = root / "knowledge/novacommerce" / entry["path"]
            queued = await service.queue_upload(
                tenant_id,
                source_path.read_bytes(),
                UploadMetadata(
                    slug=entry["slug"],
                    title=entry["title"],
                    document_type=entry["document_type"],
                    language=entry["language"],
                    version=entry["version"],
                    effective_date=date.fromisoformat(entry["effective_date"]),
                    filename=source_path.name,
                ),
            )
            await service.process_job(queued.ingestion_job_id, embedding)
            if entry["intent"] in {"historical", "current"}:
                await service.activate(tenant_id, queued.version_id)
    async with engine.connect() as connection:
        document_count = await connection.scalar(
            sa.select(sa.func.count())
            .select_from(knowledge_documents)
            .where(knowledge_documents.c.tenant_id == tenant_id)
        )
        version_count = await connection.scalar(
            sa.select(sa.func.count())
            .select_from(knowledge_versions)
            .join(knowledge_documents, knowledge_documents.c.id == knowledge_versions.c.document_id)
            .where(knowledge_documents.c.tenant_id == tenant_id)
        )
        chunk_count = await connection.scalar(
            sa.select(sa.func.count())
            .select_from(knowledge_chunks)
            .where(knowledge_chunks.c.tenant_id == tenant_id)
        )
        active_chunks = await connection.scalar(
            sa.select(sa.func.count())
            .select_from(knowledge_chunks)
            .join(knowledge_versions, knowledge_versions.c.id == knowledge_chunks.c.version_id)
            .where(
                knowledge_chunks.c.tenant_id == tenant_id, knowledge_versions.c.status == "active"
            )
        )
        superseded_chunks = await connection.scalar(
            sa.select(sa.func.count())
            .select_from(knowledge_chunks)
            .join(knowledge_versions, knowledge_versions.c.id == knowledge_chunks.c.version_id)
            .where(
                knowledge_chunks.c.tenant_id == tenant_id,
                knowledge_versions.c.status == "superseded",
            )
        )
    await engine.dispose()
    return {
        "document_count": int(document_count or 0),
        "version_count": int(version_count or 0),
        "chunk_count": int(chunk_count or 0),
        "active_chunk_count": int(active_chunks or 0),
        "superseded_chunk_count": int(superseded_chunks or 0),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.environ.get("VERBAOPS_DATABASE__URL"))
    parser.add_argument("--tenant-id", default="10000000-0000-0000-0000-000000000002")
    parser.add_argument(
        "--gateway-url",
        default=os.environ.get("VERBAOPS_LLM__BASE_URL", "http://localhost:14000/v1"),
    )
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or VERBAOPS_DATABASE__URL is required")
    print(
        json.dumps(
            asyncio.run(
                ingest(
                    Path(__file__).resolve().parents[1],
                    args.database_url,
                    UUID(args.tenant_id),
                    args.gateway_url,
                )
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
