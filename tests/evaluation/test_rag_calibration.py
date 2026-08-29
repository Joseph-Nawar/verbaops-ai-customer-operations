from collections.abc import Sequence
from datetime import date
from uuid import UUID

import pytest

from verbaops.evaluation.rag_runner import (
    CalibrationError,
    FrozenRetrievalParameters,
    RetrievalStrategy,
    calibrate_threshold,
    retrieve_frozen_strategy,
    select_strategy,
    validate_holdout_provenance,
)
from verbaops.retrieval.models import (
    DenseHit,
    FusedCandidate,
    KnowledgeHit,
    LexicalHit,
    RerankScore,
)


def _hit(index: int) -> KnowledgeHit:
    return KnowledgeHit(
        chunk_id=UUID(int=index + 1),
        tenant_id=UUID(int=10),
        document_id=UUID(int=20),
        version_id=UUID(int=30),
        document_title="Policy",
        document_slug="shipping-policy",
        document_version="2026.1",
        section="Delivery methods",
        effective_date=date(2026, 1, 1),
        language="en",
        content=f"content {index}",
    )


def test_strategy_parameters_are_frozen_to_m5b_contract() -> None:
    params = FrozenRetrievalParameters()
    assert params.as_dict() == {
        "dense_limit": 20,
        "lexical_limit": 20,
        "rrf_k": 60,
        "fused_limit": 20,
        "rerank_limit": 20,
        "final_limit": 5,
    }
    assert [item.value for item in RetrievalStrategy] == [
        "dense",
        "lexical",
        "hybrid_rrf",
        "hybrid_rrf_rerank",
    ]


@pytest.mark.asyncio
async def test_strategy_adapter_reuses_dense_lexical_rrf_and_rerank_primitives() -> None:
    dense = [DenseHit(_hit(1), 1, 0.9), DenseHit(_hit(2), 2, 0.8)]
    lexical = [LexicalHit(_hit(2), 1, 0.7), LexicalHit(_hit(3), 2, 0.6)]
    hybrid = await retrieve_frozen_strategy(
        "shipping",
        dense=dense,
        lexical=lexical,
        strategy=RetrievalStrategy.HYBRID_RRF,
    )
    assert len(hybrid.candidates) == 3
    assert hybrid.candidates[0].chunk.chunk_id == UUID(int=3)

    async def rerank(query: str, candidates: Sequence[FusedCandidate]) -> list[RerankScore]:
        return [
            RerankScore(index=index, score=float(len(candidates) - index))
            for index in range(len(candidates))
        ]

    reranked = await retrieve_frozen_strategy(
        "shipping",
        dense=dense,
        lexical=lexical,
        strategy=RetrievalStrategy.HYBRID_RRF_RERANK,
        rerank=rerank,
    )
    assert reranked.candidates[0].chunk.chunk_id == UUID(int=3)


def test_selection_applies_preregistered_tie_breaks() -> None:
    result = select_strategy(
        {
            "dense": {"recall_at_5": 0.80, "ndcg_at_5": 0.70, "mrr": 0.60, "p95_ms": 90},
            "lexical": {"recall_at_5": 0.81, "ndcg_at_5": 0.60, "mrr": 0.90, "p95_ms": 50},
            "hybrid_rrf": {"recall_at_5": 0.80, "ndcg_at_5": 0.73, "mrr": 0.65, "p95_ms": 70},
            "hybrid_rrf_rerank": {
                "recall_at_5": 0.80,
                "ndcg_at_5": 0.72,
                "mrr": 0.65,
                "p95_ms": 80,
            },
        }
    )
    assert result.strategy == "hybrid_rrf"


def test_calibration_requires_ninety_percent_no_answer_abstention() -> None:
    observations = [(False, 0.1)] * 11 + [(False, 0.2)] + [(True, 0.9)] * 84
    result = calibrate_threshold(observations)
    assert result.threshold == 0.2
    assert result.no_answer_abstained == 12
    assert result.answerable_accepted == 84


def test_calibration_reports_failure_when_no_threshold_is_eligible() -> None:
    with pytest.raises(CalibrationError, match="90%"):
        calibrate_threshold([(True, 0.1)] * 12 + [(True, 0.9)] * 84)


def test_holdout_requires_frozen_matching_selection() -> None:
    with pytest.raises(ValueError, match="dataset SHA"):
        validate_holdout_provenance(
            {
                "dataset_sha256": "a",
                "knowledge_manifest_sha256": "b",
                "strategy": "dense",
                "calibrated_threshold": 0.5,
            },
            dataset_sha256="different",
            knowledge_sha256="b",
        )
