"""Hybrid retrieval orchestration and audit persistence."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from time import perf_counter
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from verbaops.knowledge.embeddings import EmbeddingProtocolError
from verbaops.knowledge.profiles import EMBEDDING_MODEL, EMBEDDING_PROFILE, format_query
from verbaops.retrieval.models import (
    FusedCandidate,
    RerankScore,
    RetrievalEvidence,
    RetrievalResult,
    RetrievalStatus,
)
from verbaops.retrieval.repository import RetrievalRepository
from verbaops.retrieval.reranker import RerankerProtocolError
from verbaops.retrieval.rrf import reciprocal_rank_fusion

RETRIEVAL_VERSION = "knowledge-retrieval-v1"
RERANKER_MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
DENSE_LIMIT = 20
LEXICAL_LIMIT = 20
RRF_K = 60
FUSED_LIMIT = 20
FINAL_LIMIT = 5
MIN_RERANK_SCORE = 0.5


class EmbeddingProvider(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class RerankerProvider(Protocol):
    async def rerank(
        self, query: str, candidates: Sequence[FusedCandidate]
    ) -> list[RerankScore]: ...


class RetrievalService:
    """Run hybrid retrieval while keeping external inference outside DB transactions."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        repository: RetrievalRepository | None = None,
        embedding_client: EmbeddingProvider,
        reranker_client: RerankerProvider,
        min_rerank_score: float = MIN_RERANK_SCORE,
    ) -> None:
        self._session_factory = session_factory
        self._repository = repository or RetrievalRepository()
        self._embedding_client = embedding_client
        self._reranker_client = reranker_client
        self._min_rerank_score = min_rerank_score

    async def retrieve(
        self,
        *,
        agent_run_id: UUID,
        tenant_id: UUID,
        query: str,
        language: str = "en",
        sequence: int = 1,
    ) -> RetrievalResult:
        started = perf_counter()
        invocation_id = uuid4()
        normalized_query = " ".join(query.split())
        try:
            vectors = await self._embedding_client.embed([format_query(normalized_query)])
            if len(vectors) != 1:
                raise EmbeddingProtocolError()
        except Exception:
            await self._persist(
                invocation_id=invocation_id,
                agent_run_id=agent_run_id,
                tenant_id=tenant_id,
                sequence=sequence,
                language=language,
                status=RetrievalStatus.FAILED,
                dense=[],
                lexical=[],
                fused=[],
                selected=[],
                top_score=None,
                latency_ms=_latency_ms(started),
                error_code="embedding_unavailable",
            )
            return RetrievalResult(
                invocation_id=invocation_id,
                status=RetrievalStatus.UNAVAILABLE,
                evidence=(),
                error_code="embedding_unavailable",
            )

        async with self._session_factory() as session, session.begin():
            connection = await session.connection()
            dense = await self._repository.search_dense(
                connection,
                tenant_id=tenant_id,
                vector=vectors[0],
                embedding_profile=EMBEDDING_PROFILE,
                language=language,
                limit=DENSE_LIMIT,
            )
            lexical = await self._repository.search_lexical(
                connection,
                tenant_id=tenant_id,
                query=normalized_query,
                language=language,
                limit=LEXICAL_LIMIT,
            )
        fused = reciprocal_rank_fusion(dense, lexical, k=RRF_K, limit=FUSED_LIMIT)

        try:
            rerank_scores = await self._reranker_client.rerank(normalized_query, fused)
        except Exception:
            await self._persist(
                invocation_id=invocation_id,
                agent_run_id=agent_run_id,
                tenant_id=tenant_id,
                sequence=sequence,
                language=language,
                status=RetrievalStatus.FAILED,
                dense=dense,
                lexical=lexical,
                fused=fused,
                selected=[],
                top_score=None,
                latency_ms=_latency_ms(started),
                error_code="reranker_unavailable",
            )
            return RetrievalResult(
                invocation_id=invocation_id,
                status=RetrievalStatus.UNAVAILABLE,
                evidence=(),
                error_code="reranker_unavailable",
            )

        reranked = _apply_rerank_scores(fused, rerank_scores)
        top_score = reranked[0].rerank_score if reranked else None
        selected = []
        if top_score is not None and top_score >= self._min_rerank_score:
            selected = [
                replace(candidate, selected=True, evidence_key=f"K{index}")
                for index, candidate in enumerate(reranked[:FINAL_LIMIT], start=1)
            ]
        persisted_candidates = _merge_selected(reranked, selected)
        status = RetrievalStatus.SUCCEEDED if selected else RetrievalStatus.INSUFFICIENT
        await self._persist(
            invocation_id=invocation_id,
            agent_run_id=agent_run_id,
            tenant_id=tenant_id,
            sequence=sequence,
            language=language,
            status=status,
            dense=dense,
            lexical=lexical,
            fused=persisted_candidates,
            selected=selected,
            top_score=top_score,
            latency_ms=_latency_ms(started),
            error_code=None,
        )
        return RetrievalResult(
            invocation_id=invocation_id,
            status=status,
            evidence=tuple(_evidence(candidate) for candidate in selected),
            top_score=top_score,
        )

    async def _persist(
        self,
        *,
        invocation_id: UUID,
        agent_run_id: UUID,
        tenant_id: UUID,
        sequence: int,
        language: str,
        status: RetrievalStatus,
        dense: Sequence[object],
        lexical: Sequence[object],
        fused: Sequence[FusedCandidate],
        selected: Sequence[FusedCandidate],
        top_score: float | None,
        latency_ms: float,
        error_code: str | None,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            connection = await session.connection()
            await self._repository.persist_trace(
                connection,
                invocation_id=invocation_id,
                agent_run_id=agent_run_id,
                tenant_id=tenant_id,
                sequence=sequence,
                retrieval_version=RETRIEVAL_VERSION,
                strategy="hybrid_rrf",
                language=language,
                status=(
                    "failed"
                    if status in (RetrievalStatus.UNAVAILABLE, RetrievalStatus.FAILED)
                    else status.value
                ),
                dense_candidate_count=len(dense),
                lexical_candidate_count=len(lexical),
                fused_candidate_count=len(fused),
                reranked_candidate_count=sum(
                    1 for candidate in fused if candidate.rerank_rank is not None
                ),
                selected_count=len(selected),
                top_score=top_score,
                latency_ms=latency_ms,
                embedding_model=EMBEDDING_MODEL,
                reranker_model=RERANKER_MODEL,
                error_code=error_code,
                candidates=fused,
            )


def _apply_rerank_scores(
    candidates: Sequence[FusedCandidate], scores: Sequence[RerankScore]
) -> list[FusedCandidate]:
    if len(scores) != len(candidates) or {score.index for score in scores} != set(
        range(len(candidates))
    ):
        raise RerankerProtocolError()
    by_index = {score.index: score.score for score in scores}
    ranked = sorted(
        enumerate(candidates),
        key=lambda item: (-by_index[item[0]], str(item[1].chunk.chunk_id)),
    )
    return [
        replace(
            candidate,
            rerank_rank=rank,
            rerank_score=by_index[index],
        )
        for rank, (index, candidate) in enumerate(ranked, start=1)
    ]


def _merge_selected(
    candidates: Sequence[FusedCandidate], selected: Sequence[FusedCandidate]
) -> list[FusedCandidate]:
    selected_by_chunk = {candidate.chunk.chunk_id: candidate for candidate in selected}
    return [selected_by_chunk.get(candidate.chunk.chunk_id, candidate) for candidate in candidates]


def _evidence(candidate: FusedCandidate) -> RetrievalEvidence:
    return RetrievalEvidence(
        evidence_key=candidate.evidence_key or "",
        chunk_id=candidate.chunk.chunk_id,
        document_id=candidate.chunk.document_id,
        version_id=candidate.chunk.version_id,
        document_title=candidate.chunk.document_title,
        document_slug=candidate.chunk.document_slug,
        document_version=candidate.chunk.document_version,
        section=candidate.chunk.section,
        effective_date=candidate.chunk.effective_date,
        content=candidate.chunk.content,
        chunk_index=candidate.chunk.chunk_index,
    )


def _latency_ms(started: float) -> float:
    return max(0.0, (perf_counter() - started) * 1000)


__all__ = [
    "DENSE_LIMIT",
    "EMBEDDING_PROFILE",
    "FINAL_LIMIT",
    "FUSED_LIMIT",
    "LEXICAL_LIMIT",
    "MIN_RERANK_SCORE",
    "RETRIEVAL_VERSION",
    "RRF_K",
    "RetrievalService",
    "RetrievalStatus",
]
