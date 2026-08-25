from datetime import date
from uuid import UUID

import pytest

from verbaops.retrieval.models import DenseHit, KnowledgeHit, LexicalHit
from verbaops.retrieval.rrf import (
    dense_similarity_from_cosine_distance,
    reciprocal_rank_fusion,
)


def hit(chunk_id: str, *, dense: float | None = None, lexical: float | None = None) -> KnowledgeHit:
    return KnowledgeHit(
        chunk_id=UUID(chunk_id),
        tenant_id=UUID("10000000-0000-0000-0000-000000000001"),
        document_id=UUID("20000000-0000-0000-0000-000000000001"),
        version_id=UUID("30000000-0000-0000-0000-000000000001"),
        document_title="Returns Policy",
        document_slug="returns-policy",
        document_version="2026.1",
        section="Return Window",
        effective_date=date(2026, 1, 1),
        language="en",
        content="Return window is 30 days.",
    )


def test_dense_cosine_distance_converts_to_similarity_score() -> None:
    assert dense_similarity_from_cosine_distance(0.0) == pytest.approx(1.0)
    assert dense_similarity_from_cosine_distance(0.25) == pytest.approx(0.75)


def test_rrf_uses_exact_k60_math_and_deterministic_ties() -> None:
    first = hit("00000000-0000-0000-0000-000000000002")
    second = hit("00000000-0000-0000-0000-000000000001")
    dense = [DenseHit(first, rank=1, score=0.9), DenseHit(second, rank=2, score=0.8)]
    lexical = [LexicalHit(second, rank=1, score=0.9), LexicalHit(first, rank=2, score=0.8)]

    fused = reciprocal_rank_fusion(dense, lexical)

    assert [candidate.chunk.chunk_id for candidate in fused] == [second.chunk_id, first.chunk_id]
    assert fused[0].rrf_score == pytest.approx((1 / 61) + (1 / 62))
    assert fused[1].rrf_score == pytest.approx((1 / 61) + (1 / 62))
    assert fused[0].rrf_rank == 1
    assert fused[1].rrf_rank == 2
