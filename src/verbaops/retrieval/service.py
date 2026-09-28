"""Hybrid retrieval orchestration and audit persistence."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from time import perf_counter
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from verbaops.knowledge.embeddings import EmbeddingProtocolError
from verbaops.knowledge.profiles import EMBEDDING_PROFILE, format_query
from verbaops.retrieval.models import (
    FusedCandidate,
    RerankScore,
    RetrievalEvidence,
    RetrievalResult,
    RetrievalStatus,
)
from verbaops.retrieval.profile import M5B_RETRIEVAL_PROFILE, RetrievalProfile
from verbaops.retrieval.repository import RetrievalRepository
from verbaops.retrieval.reranker import RerankerProtocolError
from verbaops.retrieval.rrf import reciprocal_rank_fusion

RETRIEVAL_VERSION = M5B_RETRIEVAL_PROFILE.version
DENSE_LIMIT = M5B_RETRIEVAL_PROFILE.dense_limit
LEXICAL_LIMIT = M5B_RETRIEVAL_PROFILE.lexical_limit
RRF_K = M5B_RETRIEVAL_PROFILE.rrf_k
FUSED_LIMIT = M5B_RETRIEVAL_PROFILE.fused_limit
FINAL_LIMIT = M5B_RETRIEVAL_PROFILE.final_limit
MIN_RERANK_SCORE = M5B_RETRIEVAL_PROFILE.threshold


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
        reranker_client: RerankerProvider | None,
        profile: RetrievalProfile = M5B_RETRIEVAL_PROFILE,
        min_rerank_score: float | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._repository = repository or RetrievalRepository()
        self._embedding_client = embedding_client
        self._reranker_client = reranker_client
        self._profile = profile
        self._min_rerank_score = profile.threshold if min_rerank_score is None else min_rerank_score

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
                embedding_profile=self._profile.embedding_profile,
                language=language,
                limit=self._profile.dense_limit,
            )
            lexical = await self._repository.search_lexical(
                connection,
                tenant_id=tenant_id,
                query=normalized_query,
                language=language,
                limit=self._profile.lexical_limit,
            )
        fused = reciprocal_rank_fusion(
            dense,
            lexical,
            k=self._profile.rrf_k,
            limit=self._profile.fused_limit,
        )

        ranked = fused
        if self._profile.uses_reranker:
            if self._reranker_client is None:
                return await self._persist_unavailable(
                    invocation_id=invocation_id,
                    agent_run_id=agent_run_id,
                    tenant_id=tenant_id,
                    sequence=sequence,
                    language=language,
                    dense=dense,
                    lexical=lexical,
                    fused=fused,
                    started=started,
                )
            try:
                rerank_scores = await self._reranker_client.rerank(normalized_query, fused)
            except Exception:
                return await self._persist_unavailable(
                    invocation_id=invocation_id,
                    agent_run_id=agent_run_id,
                    tenant_id=tenant_id,
                    sequence=sequence,
                    language=language,
                    dense=dense,
                    lexical=lexical,
                    fused=fused,
                    started=started,
                )
            ranked = _apply_rerank_scores(fused, rerank_scores)
        top_score = _top_score(ranked, self._profile.uses_reranker)
        selected = []
        if top_score is not None and top_score >= self._min_rerank_score:
            selected = [
                replace(candidate, selected=True, evidence_key=f"K{index}")
                for index, candidate in enumerate(ranked[: self._profile.final_limit], start=1)
            ]
        persisted_candidates = _merge_selected(ranked, selected)
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

    async def _persist_unavailable(
        self,
        *,
        invocation_id: UUID,
        agent_run_id: UUID,
        tenant_id: UUID,
        sequence: int,
        language: str,
        dense: Sequence[object],
        lexical: Sequence[object],
        fused: Sequence[FusedCandidate],
        started: float,
    ) -> RetrievalResult:
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
                retrieval_version=self._profile.version,
                strategy=self._profile.strategy,
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
                embedding_model=self._profile.embedding_model,
                reranker_model=self._profile.reranker_model,
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


def _top_score(candidates: Sequence[FusedCandidate], reranked: bool) -> float | None:
    if not candidates:
        return None
    return candidates[0].rerank_score if reranked else candidates[0].rrf_score


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
