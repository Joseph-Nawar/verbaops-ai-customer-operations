from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from uuid import UUID

import pytest

from verbaops.retrieval.evidence_gate import (
    DenseSimilarityGateScorer,
    RrfTopScoreGateScorer,
    TopEvidenceCrossEncoderGateScorer,
)
from verbaops.retrieval.models import (
    FusedCandidate,
    KnowledgeHit,
    RerankScore,
)

TENANT_ID = UUID("60000000-0000-0000-0000-000000000001")


def _candidates(count: int, *, lexical_only: bool = False) -> list[FusedCandidate]:
    result = []
    for index in range(count):
        chunk = KnowledgeHit(
            chunk_id=UUID(int=index + 1),
            tenant_id=TENANT_ID,
            document_id=UUID(int=100 + index),
            version_id=UUID(int=200 + index),
            document_title=f"Policy {index}",
            document_slug=f"policy-{index}",
            document_version="2026.1",
            section="Returns",
            effective_date=date(2026, 1, 1),
            language="en",
            content=f"Policy content {index}.",
        )
        result.append(
            FusedCandidate(
                chunk=chunk,
                dense_rank=None if lexical_only else index + 1,
                dense_score=None if lexical_only else 0.8,
                lexical_rank=index + 1,
                lexical_score=0.2,
                rrf_rank=index + 1,
                rrf_score=1 / (60 + index + 1),
            )
        )
    return result


class FakeSession:
    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def begin(self) -> FakeSession:
        return self

    async def connection(self) -> object:
        return object()


class FakeEmbeddingRepository:
    def __init__(self, values: dict[UUID, list[float]]) -> None:
        self.values = values
        self.requested: list[UUID] = []

    async def fetch_candidate_embeddings(
        self,
        _connection: object,
        *,
        tenant_id: UUID,
        chunk_ids: Sequence[UUID],
        embedding_profile: str,
    ) -> dict[UUID, list[float]]:
        assert tenant_id == TENANT_ID
        assert embedding_profile == "multilingual-e5-base-v1"
        self.requested = list(chunk_ids)
        return {
            chunk_id: self.values[chunk_id] for chunk_id in chunk_ids if chunk_id in self.values
        }


class FakeCrossEncoder:
    def __init__(self, scores: Sequence[float]) -> None:
        self.scores = list(scores)
        self.received: list[FusedCandidate] = []

    async def rerank(self, _query: str, candidates: Sequence[FusedCandidate]) -> list[RerankScore]:
        self.received = list(candidates)
        return [RerankScore(index=index, score=score) for index, score in enumerate(self.scores)]


def _session_factory() -> FakeSession:
    return FakeSession()


@pytest.mark.asyncio
async def test_dense_gate_scores_exact_final_candidates_including_lexical_only_entries() -> None:
    candidates = _candidates(5, lexical_only=True)
    repository = FakeEmbeddingRepository(
        {candidate.chunk.chunk_id: [1.0] + [0.0] * 767 for candidate in candidates}
    )
    scorer = DenseSimilarityGateScorer(
        _session_factory,
        repository=repository,
        embedding_profile="multilingual-e5-base-v1",
    )

    result = await scorer.score("query", [1.0] + [0.0] * 767, candidates)

    assert result.confidence == 1.0
    assert result.candidate_scores == (1.0,) * 5
    assert repository.requested == [candidate.chunk.chunk_id for candidate in candidates]
    assert set(result.component_latency_ms) == {
        "e5_candidate_vector_fetch",
        "e5_cosine_scoring",
    }


@pytest.mark.asyncio
async def test_dense_gate_rejects_when_any_supplied_candidate_lacks_its_stored_embedding() -> None:
    candidates = _candidates(5, lexical_only=True)
    repository = FakeEmbeddingRepository({candidates[0].chunk.chunk_id: [1.0] + [0.0] * 767})
    scorer = DenseSimilarityGateScorer(
        _session_factory,
        repository=repository,
        embedding_profile="multilingual-e5-base-v1",
    )

    result = await scorer.score("query", [1.0] + [0.0] * 767, candidates)

    assert result.confidence is None
    assert result.candidate_scores == ()


@pytest.mark.asyncio
async def test_cross_encoder_gate_scores_exactly_the_same_final_five_without_reranking_them() -> (
    None
):
    candidates = _candidates(5)
    cross_encoder = FakeCrossEncoder([0.1, 0.4, 0.2, 0.3, 0.05])
    scorer = TopEvidenceCrossEncoderGateScorer(cross_encoder)

    result = await scorer.score("query", [0.0] * 768, candidates)

    assert result.confidence == 0.4
    assert result.candidate_scores == (0.1, 0.4, 0.2, 0.3, 0.05)
    assert cross_encoder.received == candidates
    assert "cross_encoder_scoring" in result.component_latency_ms


@pytest.mark.asyncio
async def test_cross_encoder_gate_fails_closed_if_more_than_five_candidates_are_supplied() -> None:
    cross_encoder = FakeCrossEncoder([0.1] * 6)
    scorer = TopEvidenceCrossEncoderGateScorer(cross_encoder)

    result = await scorer.score("query", [0.0] * 768, _candidates(6))

    assert result.confidence is None
    assert cross_encoder.received == []


@pytest.mark.asyncio
async def test_rrf_gate_uses_the_existing_first_candidate_score_and_keeps_order() -> None:
    candidates = _candidates(5)

    result = await RrfTopScoreGateScorer().score("query", [0.0] * 768, candidates)

    assert result.confidence == candidates[0].rrf_score
    assert result.candidate_scores == tuple(candidate.rrf_score for candidate in candidates)
    assert result.component_latency_ms == {}
