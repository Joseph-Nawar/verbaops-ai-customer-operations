"""Tenant-scoped PostgreSQL dense and lexical retrieval queries."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from verbaops.knowledge.profiles import EMBEDDING_DIMENSION
from verbaops.knowledge.repository_tables import (
    knowledge_chunks,
    knowledge_documents,
    knowledge_versions,
)
from verbaops.retrieval.models import DenseHit, KnowledgeHit, LexicalHit
from verbaops.retrieval.rrf import dense_similarity_from_cosine_distance


class RetrievalRepository:
    """Read-only retrieval statements with the tenant boundary in SQL."""

    async def search_dense(
        self,
        connection: AsyncConnection,
        *,
        tenant_id: UUID,
        vector: Sequence[float],
        embedding_profile: str,
        language: str,
        limit: int = 20,
    ) -> list[DenseHit]:
        if len(vector) != EMBEDDING_DIMENSION:
            raise ValueError("retrieval vector has the wrong dimension")
        distance = knowledge_chunks.c.embedding.cosine_distance(list(vector)).label("distance")
        statement = (
            self._base_statement(tenant_id=tenant_id, language=language)
            .add_columns(distance)
            .where(knowledge_versions.c.embedding_profile == embedding_profile)
            .order_by(distance.asc(), knowledge_chunks.c.id.asc())
            .limit(limit)
        )
        rows = (await connection.execute(statement)).mappings().all()
        return [
            DenseHit(
                chunk=_knowledge_hit(row),
                rank=rank,
                score=dense_similarity_from_cosine_distance(float(row["distance"])),
            )
            for rank, row in enumerate(rows, start=1)
        ]

    async def search_lexical(
        self,
        connection: AsyncConnection,
        *,
        tenant_id: UUID,
        query: str,
        language: str,
        limit: int = 20,
    ) -> list[LexicalHit]:
        ts_query = sa.func.websearch_to_tsquery("english", query)
        score = sa.func.ts_rank_cd(knowledge_chunks.c.search_vector, ts_query).label("score")
        statement = (
            self._base_statement(tenant_id=tenant_id, language=language)
            .add_columns(score)
            .where(knowledge_chunks.c.search_vector.op("@@")(ts_query))
            .order_by(score.desc(), knowledge_chunks.c.id.asc())
            .limit(limit)
        )
        rows = (await connection.execute(statement)).mappings().all()
        return [
            LexicalHit(chunk=_knowledge_hit(row), rank=rank, score=float(row["score"]))
            for rank, row in enumerate(rows, start=1)
        ]

    @staticmethod
    def _base_statement(*, tenant_id: UUID, language: str) -> sa.Select[tuple[object, ...]]:
        return (
            sa.select(
                knowledge_chunks.c.id.label("chunk_id"),
                knowledge_chunks.c.tenant_id,
                knowledge_chunks.c.document_id,
                knowledge_chunks.c.version_id,
                knowledge_documents.c.title.label("document_title"),
                knowledge_documents.c.slug.label("document_slug"),
                knowledge_versions.c.version.label("document_version"),
                knowledge_chunks.c.section,
                knowledge_versions.c.effective_date,
                knowledge_chunks.c.language,
                knowledge_chunks.c.content,
            )
            .select_from(
                knowledge_chunks.join(
                    knowledge_versions,
                    knowledge_versions.c.id == knowledge_chunks.c.version_id,
                ).join(
                    knowledge_documents,
                    knowledge_documents.c.id == knowledge_versions.c.document_id,
                )
            )
            .where(
                knowledge_chunks.c.tenant_id == tenant_id,
                knowledge_chunks.c.language == language,
                knowledge_documents.c.language == language,
                knowledge_versions.c.status == "active",
                knowledge_versions.c.effective_date <= sa.func.current_date(),
            )
        )


def _knowledge_hit(row: sa.RowMapping) -> KnowledgeHit:
    return KnowledgeHit(
        chunk_id=row["chunk_id"],
        tenant_id=row["tenant_id"],
        document_id=row["document_id"],
        version_id=row["version_id"],
        document_title=row["document_title"],
        document_slug=row["document_slug"],
        document_version=row["document_version"],
        section=row["section"],
        effective_date=row["effective_date"],
        language=row["language"],
        content=row["content"],
    )


__all__ = ["RetrievalRepository"]
