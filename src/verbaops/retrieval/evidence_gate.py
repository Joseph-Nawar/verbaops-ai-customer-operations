"""Opt-in M5D evidence-confidence scorers over frozen hybrid candidates."""

from __future__ import annotations

import math
from collections.abc import Sequence
from enum import StrEnum
from time import perf_counter
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from verbaops.knowledge.profiles import EMBEDDING_DIMENSION, EMBEDDING_PROFILE
from verbaops.retrieval.models import EvidenceGateScore, FusedCandidate, RerankScore
from verbaops.retrieval.repository import RetrievalRepository


class EvidenceGate(StrEnum):
    G0_CURRENT_RRF = "G0_CURRENT_RRF"
    G1_DENSE_SIMILARITY = "G1_DENSE_SIMILARITY"
    G2_TOP_EVIDENCE_CROSS_ENCODER = "G2_TOP_EVIDENCE_CROSS_ENCODER"


class CrossEncoder(Protocol):
    async def rerank(
        self, query: str, candidates: Sequence[FusedCandidate]
    ) -> list[RerankScore]: ...


class RrfTopScoreGateScorer:
    """Expose the top score from the unchanged hybrid-RRF ranking."""

    async def score(
        self,
        _query: str,
        _query_embedding: Sequence[float],
        candidates: Sequence[FusedCandidate],
    ) -> EvidenceGateScore:
        if not candidates:
            return EvidenceGateScore(confidence=None)
        return EvidenceGateScore(
            confidence=candidates[0].rrf_score,
            candidate_scores=tuple(candidate.rrf_score for candidate in candidates),
        )


class DenseSimilarityGateScorer:
    """Score each supplied candidate by E5 cosine without changing candidate order."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        repository: RetrievalRepository | None = None,
        embedding_profile: str = EMBEDDING_PROFILE,
    ) -> None:
        self._session_factory = session_factory
        self._repository = repository or RetrievalRepository()
        self._embedding_profile = embedding_profile

    async def score(
        self,
        _query: str,
        query_embedding: Sequence[float],
        candidates: Sequence[FusedCandidate],
    ) -> EvidenceGateScore:
        if not candidates or len(candidates) > 5 or len(query_embedding) != EMBEDDING_DIMENSION:
            return EvidenceGateScore(confidence=None)
        tenant_ids = {candidate.chunk.tenant_id for candidate in candidates}
        if len(tenant_ids) != 1:
            return EvidenceGateScore(confidence=None)
        candidate_ids = [candidate.chunk.chunk_id for candidate in candidates]
        if len(set(candidate_ids)) != len(candidate_ids):
            return EvidenceGateScore(confidence=None)

        fetch_started = perf_counter()
        async with self._session_factory() as session, session.begin():
            connection = await session.connection()
            document_embeddings = await self._repository.fetch_candidate_embeddings(
                connection,
                tenant_id=next(iter(tenant_ids)),
                chunk_ids=candidate_ids,
                embedding_profile=self._embedding_profile,
            )
        fetch_ms = _elapsed_ms(fetch_started)
        if set(document_embeddings) != set(candidate_ids):
            return EvidenceGateScore(
                confidence=None,
                component_latency_ms={"e5_candidate_vector_fetch": fetch_ms},
            )

        score_started = perf_counter()
        similarities: list[float] = []
        try:
            for candidate_id in candidate_ids:
                similarities.append(
                    _cosine_similarity(query_embedding, document_embeddings[candidate_id])
                )
        except ValueError:
            return EvidenceGateScore(
                confidence=None,
                component_latency_ms={
                    "e5_candidate_vector_fetch": fetch_ms,
                    "e5_cosine_scoring": _elapsed_ms(score_started),
                },
            )
        return EvidenceGateScore(
            confidence=max(similarities),
            candidate_scores=tuple(similarities),
            component_latency_ms={
                "e5_candidate_vector_fetch": fetch_ms,
                "e5_cosine_scoring": _elapsed_ms(score_started),
            },
        )


class TopEvidenceCrossEncoderGateScorer:
    """Score exactly the supplied final five; never reorder them."""

    def __init__(self, cross_encoder: CrossEncoder) -> None:
        self._cross_encoder = cross_encoder

    async def score(
        self,
        query: str,
        _query_embedding: Sequence[float],
        candidates: Sequence[FusedCandidate],
    ) -> EvidenceGateScore:
        if not candidates or len(candidates) > 5:
            return EvidenceGateScore(confidence=None)
        started = perf_counter()
        scores = await self._cross_encoder.rerank(query, candidates)
        elapsed_ms = _elapsed_ms(started)
        by_index = {item.index: item.score for item in scores}
        if len(by_index) != len(candidates) or set(by_index) != set(range(len(candidates))):
            return EvidenceGateScore(
                confidence=None,
                component_latency_ms={"cross_encoder_scoring": elapsed_ms},
            )
        ordered_scores = tuple(by_index[index] for index in range(len(candidates)))
        if not all(math.isfinite(score) for score in ordered_scores):
            return EvidenceGateScore(
                confidence=None,
                component_latency_ms={"cross_encoder_scoring": elapsed_ms},
            )
        return EvidenceGateScore(
            confidence=max(ordered_scores),
            candidate_scores=ordered_scores,
            component_latency_ms={"cross_encoder_scoring": elapsed_ms},
        )


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != EMBEDDING_DIMENSION or len(right) != EMBEDDING_DIMENSION:
        raise ValueError("E5 candidate embedding dimension mismatch")
    if not all(math.isfinite(value) for value in (*left, *right)):
        raise ValueError("E5 candidate embedding contains a non-finite value")
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        raise ValueError("E5 candidate embedding has zero norm")
    return dot / (left_norm * right_norm)


def _elapsed_ms(started: float) -> float:
    return round(max(0.0, (perf_counter() - started) * 1000), 6)


__all__ = [
    "DenseSimilarityGateScorer",
    "EvidenceGate",
    "RrfTopScoreGateScorer",
    "TopEvidenceCrossEncoderGateScorer",
]
