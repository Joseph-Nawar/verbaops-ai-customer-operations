"""Tenant-scoped PostgreSQL dense and lexical retrieval queries."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from verbaops.knowledge.profiles import EMBEDDING_DIMENSION
from verbaops.knowledge.repository_tables import (
    knowledge_chunks,
    knowledge_documents,
    knowledge_versions,
    retrieval_candidates,
    retrieval_invocations,
)
from verbaops.retrieval.models import DenseHit, FusedCandidate, KnowledgeHit, LexicalHit
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

    async def persist_trace(
        self,
        connection: AsyncConnection,
        *,
        invocation_id: UUID,
        agent_run_id: UUID,
        tenant_id: UUID,
        sequence: int,
        retrieval_version: str,
        strategy: str,
        language: str,
        status: str,
        dense_candidate_count: int,
        lexical_candidate_count: int,
        fused_candidate_count: int,
        reranked_candidate_count: int,
        selected_count: int,
        top_score: float | None,
        latency_ms: float,
        embedding_model: str | None,
        reranker_model: str | None,
        error_code: str | None,
        candidates: Sequence[FusedCandidate],
    ) -> None:
        created_at = datetime.now(UTC)
        await connection.execute(
            retrieval_invocations.insert().values(
                id=invocation_id,
                agent_run_id=agent_run_id,
                tenant_id=tenant_id,
                sequence=sequence,
                retrieval_version=retrieval_version,
                strategy=strategy,
                language=language,
                status=status,
                dense_candidate_count=dense_candidate_count,
                lexical_candidate_count=lexical_candidate_count,
                fused_candidate_count=fused_candidate_count,
                reranked_candidate_count=reranked_candidate_count,
                selected_count=selected_count,
                top_score=top_score,
                latency_ms=latency_ms,
                embedding_model=embedding_model,
                reranker_model=reranker_model,
                error_code=error_code,
                created_at=created_at,
            )
        )
        if candidates:
            await connection.execute(
                retrieval_candidates.insert().values(
                    [
                        {
                            "id": uuid4(),
                            "retrieval_invocation_id": invocation_id,
                            "chunk_id": candidate.chunk.chunk_id,
                            "dense_rank": candidate.dense_rank,
                            "dense_score": candidate.dense_score,
                            "lexical_rank": candidate.lexical_rank,
                            "lexical_score": candidate.lexical_score,
                            "rrf_rank": candidate.rrf_rank,
                            "rrf_score": candidate.rrf_score,
                            "rerank_rank": candidate.rerank_rank,
                            "rerank_score": candidate.rerank_score,
                            "selected": candidate.selected,
                            "evidence_key": candidate.evidence_key,
                        }
                        for candidate in candidates
                    ]
                )
            )

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
                knowledge_documents.c.tenant_id == tenant_id,
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
