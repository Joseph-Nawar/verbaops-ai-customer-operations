"""Deterministic reciprocal-rank fusion."""

from __future__ import annotations

import math
from collections.abc import Sequence

from verbaops.retrieval.models import DenseHit, FusedCandidate, LexicalHit


def dense_similarity_from_cosine_distance(distance: float) -> float:
    """Convert pgvector cosine distance into a similarity score."""

    if not math.isfinite(distance):
        raise ValueError("cosine distance must be finite")
    return 1.0 - distance


def reciprocal_rank_fusion(
    dense: Sequence[DenseHit],
    lexical: Sequence[LexicalHit],
    *,
    k: int = 60,
    limit: int = 20,
) -> list[FusedCandidate]:
    """Fuse ranked lists without adding their raw scores."""

    if k <= 0 or limit <= 0:
        raise ValueError("k and limit must be positive")

    candidates: dict[object, FusedCandidate] = {}
    for item in dense:
        current = candidates.get(item.chunk.chunk_id)
        contribution = 1.0 / (k + item.rank)
        if current is None:
            candidates[item.chunk.chunk_id] = FusedCandidate(
                chunk=item.chunk,
                dense_rank=item.rank,
                dense_score=item.score,
                lexical_rank=None,
                lexical_score=None,
                rrf_rank=0,
                rrf_score=contribution,
            )
        else:
            candidates[item.chunk.chunk_id] = FusedCandidate(
                chunk=current.chunk,
                dense_rank=item.rank,
                dense_score=item.score,
                lexical_rank=current.lexical_rank,
                lexical_score=current.lexical_score,
                rrf_rank=0,
                rrf_score=current.rrf_score + contribution,
            )

    for item in lexical:
        current = candidates.get(item.chunk.chunk_id)
        contribution = 1.0 / (k + item.rank)
        if current is None:
            candidates[item.chunk.chunk_id] = FusedCandidate(
                chunk=item.chunk,
                dense_rank=None,
                dense_score=None,
                lexical_rank=item.rank,
                lexical_score=item.score,
                rrf_rank=0,
                rrf_score=contribution,
            )
        else:
            candidates[item.chunk.chunk_id] = FusedCandidate(
                chunk=current.chunk,
                dense_rank=current.dense_rank,
                dense_score=current.dense_score,
                lexical_rank=item.rank,
                lexical_score=item.score,
                rrf_rank=0,
                rrf_score=current.rrf_score + contribution,
            )

    ordered = sorted(
        candidates.values(),
        key=lambda item: (-item.rrf_score, str(item.chunk.chunk_id)),
    )[:limit]
    return [
        FusedCandidate(
            chunk=item.chunk,
            dense_rank=item.dense_rank,
            dense_score=item.dense_score,
            lexical_rank=item.lexical_rank,
            lexical_score=item.lexical_score,
            rrf_rank=index,
            rrf_score=item.rrf_score,
        )
        for index, item in enumerate(ordered, start=1)
    ]
