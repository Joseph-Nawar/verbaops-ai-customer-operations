"""Evaluation-owned strategy, selection, calibration, and holdout guards."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from time import perf_counter
from typing import Any

from verbaops.evaluation.rag_metrics import mean_reciprocal_rank, ndcg_at_k, recall_at_k
from verbaops.retrieval.models import DenseHit, FusedCandidate, LexicalHit, RerankScore
from verbaops.retrieval.rrf import reciprocal_rank_fusion


class RetrievalStrategy(StrEnum):
    DENSE = "dense"
    LEXICAL = "lexical"
    HYBRID_RRF = "hybrid_rrf"
    HYBRID_RRF_RERANK = "hybrid_rrf_rerank"


@dataclass(frozen=True, slots=True)
class FrozenRetrievalParameters:
    dense_limit: int = 20
    lexical_limit: int = 20
    rrf_k: int = 60
    fused_limit: int = 20
    rerank_limit: int = 20
    final_limit: int = 5

    def as_dict(self) -> dict[str, int]:
        return {
            "dense_limit": self.dense_limit,
            "lexical_limit": self.lexical_limit,
            "rrf_k": self.rrf_k,
            "fused_limit": self.fused_limit,
            "rerank_limit": self.rerank_limit,
            "final_limit": self.final_limit,
        }


@dataclass(frozen=True, slots=True)
class SelectionDecision:
    strategy: str
    rationale: str


class CalibrationError(ValueError):
    """No observed dev threshold satisfies the pre-registered guardrail."""


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    threshold: float
    no_answer_abstained: int
    no_answer_total: int
    answerable_accepted: int
    answerable_total: int

    @property
    def no_answer_accuracy(self) -> float:
        return self.no_answer_abstained / self.no_answer_total

    @property
    def answerable_acceptance(self) -> float:
        return self.answerable_accepted / self.answerable_total

    def as_dict(self) -> dict[str, Any]:
        return {
            "threshold": self.threshold,
            "no_answer_abstained": self.no_answer_abstained,
            "no_answer_total": self.no_answer_total,
            "answerable_accepted": self.answerable_accepted,
            "answerable_total": self.answerable_total,
        }


@dataclass(frozen=True, slots=True)
class RetrievalRun:
    strategy: str
    candidates: tuple[FusedCandidate, ...]
    top_score: float | None
    stage_latency_ms: dict[str, float]


@dataclass(frozen=True, slots=True)
class StrategyMetrics:
    strategy: str
    answerable_count: int
    recall_at_1: float | None
    recall_at_5: float | None
    mrr: float | None
    ndcg_at_5: float | None
    retrieval_p50_ms: float | None
    retrieval_p95_ms: float | None

    def as_dict(self) -> dict[str, float | int | str | None]:
        return {
            "strategy": self.strategy,
            "answerable_count": self.answerable_count,
            "recall_at_1": self.recall_at_1,
            "recall_at_5": self.recall_at_5,
            "mrr": self.mrr,
            "ndcg_at_5": self.ndcg_at_5,
            "retrieval_p50_ms": self.retrieval_p50_ms,
            "retrieval_p95_ms": self.retrieval_p95_ms,
        }


RerankFunction = Callable[[str, Sequence[FusedCandidate]], Awaitable[Sequence[RerankScore]]]
DEFAULT_PARAMETERS = FrozenRetrievalParameters()


async def retrieve_frozen_strategy(
    query: str,
    *,
    dense: Sequence[DenseHit],
    lexical: Sequence[LexicalHit],
    strategy: RetrievalStrategy,
    rerank: RerankFunction | None = None,
    parameters: FrozenRetrievalParameters = DEFAULT_PARAMETERS,
) -> RetrievalRun:
    """Apply one frozen ranking strategy to M5B-produced candidate lists."""

    started = perf_counter()
    stage_latency: dict[str, float] = {}
    if strategy is RetrievalStrategy.DENSE:
        candidates = tuple(_as_candidates(dense[: parameters.dense_limit], "dense"))
        return RetrievalRun(
            strategy.value,
            candidates[: parameters.final_limit],
            candidates[0].dense_score if candidates else None,
            {"total": _elapsed(started)},
        )
    if strategy is RetrievalStrategy.LEXICAL:
        candidates = tuple(_as_candidates(lexical[: parameters.lexical_limit], "lexical"))
        return RetrievalRun(
            strategy.value,
            candidates[: parameters.final_limit],
            candidates[0].lexical_score if candidates else None,
            {"total": _elapsed(started)},
        )
    fusion_started = perf_counter()
    fused = reciprocal_rank_fusion(
        dense[: parameters.dense_limit],
        lexical[: parameters.lexical_limit],
        k=parameters.rrf_k,
        limit=parameters.fused_limit,
    )
    stage_latency["fusion"] = _elapsed(fusion_started)
    if strategy is RetrievalStrategy.HYBRID_RRF:
        selected = tuple(fused[: parameters.final_limit])
        return RetrievalRun(
            strategy.value,
            selected,
            selected[0].rrf_score if selected else None,
            {**stage_latency, "total": _elapsed(started)},
        )
    if rerank is None:
        raise ValueError("hybrid_rrf_rerank requires a rerank function")
    rerank_started = perf_counter()
    scores = await rerank(query, fused[: parameters.rerank_limit])
    if len(scores) != len(fused[: parameters.rerank_limit]):
        raise ValueError("reranker returned an incomplete result")
    by_index = {score.index: score.score for score in scores}
    if set(by_index) != set(range(len(fused[: parameters.rerank_limit]))):
        raise ValueError("reranker indexes are not a complete permutation")
    reranked = tuple(
        sorted(
            (candidate for _, candidate in enumerate(fused[: parameters.rerank_limit])),
            key=lambda candidate: (
                -by_index[fused.index(candidate)],
                str(candidate.chunk.chunk_id),
            ),
        )
    )
    stage_latency["rerank"] = _elapsed(rerank_started)
    selected = reranked[: parameters.final_limit]
    return RetrievalRun(
        strategy.value,
        selected,
        by_index[fused.index(selected[0])] if selected else None,
        {**stage_latency, "total": _elapsed(started)},
    )


def _as_candidates(hits: Sequence[DenseHit | LexicalHit], source: str) -> list[FusedCandidate]:
    result: list[FusedCandidate] = []
    for hit in hits:
        result.append(
            FusedCandidate(
                chunk=hit.chunk,
                dense_rank=hit.rank if source == "dense" else None,
                dense_score=hit.score if source == "dense" else None,
                lexical_rank=hit.rank if source == "lexical" else None,
                lexical_score=hit.score if source == "lexical" else None,
                rrf_rank=hit.rank,
                rrf_score=0.0,
            )
        )
    return result


def _elapsed(started: float) -> float:
    return round(max(0.0, (perf_counter() - started) * 1000), 6)


def candidate_locator(candidate: FusedCandidate) -> str:
    """Return a stable benchmark locator independent of database UUIDs."""

    chunk = candidate.chunk
    return f"{chunk.document_slug}|{chunk.document_version}|{chunk.section}|{chunk.chunk_index}"


def score_retrieval_cases(cases: Sequence[Any], runs: dict[str, RetrievalRun]) -> StrategyMetrics:
    """Score answerable cases from stable candidate metadata and preserve macro semantics."""

    scored: list[tuple[float | None, float | None, float | None, float | None]] = []
    latencies: list[float] = []
    strategy = next(iter(runs.values())).strategy if runs else "unknown"
    for case in cases:
        if not case.answerable:
            continue
        run = runs[case.case_id]
        judgments = {
            f"{item.document_slug}|{item.document_version}|{item.section}|{item.chunk_index}": item.relevance_grade
            for item in case.relevance_judgments
        }
        retrieved = [candidate_locator(candidate) for candidate in run.candidates]
        scored.append(
            (
                recall_at_k(retrieved, judgments, 1),
                recall_at_k(retrieved, judgments, 5),
                mean_reciprocal_rank(retrieved, judgments),
                ndcg_at_k(retrieved, judgments, 5),
            )
        )
        total = run.stage_latency_ms.get("total")
        if total is not None:
            latencies.append(total)
    from verbaops.evaluation.rag_metrics import macro_mean
    from verbaops.evaluation.rag_reports import percentile

    return StrategyMetrics(
        strategy=strategy,
        answerable_count=len(scored),
        recall_at_1=macro_mean([item[0] for item in scored]),
        recall_at_5=macro_mean([item[1] for item in scored]),
        mrr=macro_mean([item[2] for item in scored]),
        ndcg_at_5=macro_mean([item[3] for item in scored]),
        retrieval_p50_ms=percentile(latencies, 0.5),
        retrieval_p95_ms=percentile(latencies, 0.95),
    )


def select_strategy(metrics: dict[str, dict[str, float | bool]]) -> SelectionDecision:
    """Apply the exact pre-registered lexicographic dev selection rule."""

    eligible = {
        name: values
        for name, values in metrics.items()
        if bool(values.get("invariants_passed", True))
    }
    if not eligible:
        raise ValueError("no strategy passed retrieval invariants")
    best_recall = max(float(value["recall_at_5"]) for value in eligible.values())
    recall_tied = {
        name: value
        for name, value in eligible.items()
        if best_recall - float(value["recall_at_5"]) <= 0.01 + 1e-12
    }
    best_ndcg = max(float(value["ndcg_at_5"]) for value in recall_tied.values())
    ndcg_tied = {
        name: value
        for name, value in recall_tied.items()
        if best_ndcg - float(value["ndcg_at_5"]) <= 0.02 + 1e-12
    }
    best = max(float(value["mrr"]) for value in ndcg_tied.values())
    mrr_tied = {
        name: value for name, value in ndcg_tied.items() if abs(float(value["mrr"]) - best) <= 1e-12
    }
    selected = min(
        mrr_tied, key=lambda name: (float(mrr_tied[name].get("p95_ms", float("inf"))), name)
    )
    return SelectionDecision(
        strategy=selected,
        rationale=(
            "passed invariants; maximized Recall@5; applied the 0.01 Recall@5 tie band; "
            "maximized nDCG@5 within the 0.02 tie band; then maximized MRR and used latency/name tie-break"
        ),
    )


def calibrate_threshold(observations: list[tuple[bool, float]]) -> CalibrationResult:
    """Choose an observed score threshold with <= threshold treated as abstention."""

    if not observations:
        raise CalibrationError("no dev observations available")
    candidates = sorted({float(score) for _, score in observations})
    answerable_total = sum(answerable for answerable, _ in observations)
    no_answer_total = len(observations) - answerable_total
    eligible: list[CalibrationResult] = []
    for threshold in candidates:
        no_answer_abstained = sum(
            not answerable and score <= threshold for answerable, score in observations
        )
        answerable_accepted = sum(
            answerable and score > threshold for answerable, score in observations
        )
        result = CalibrationResult(
            threshold, no_answer_abstained, no_answer_total, answerable_accepted, answerable_total
        )
        if no_answer_total and no_answer_abstained / no_answer_total >= 0.9:
            eligible.append(result)
    if not eligible:
        raise CalibrationError("no observed threshold achieves the 90% no-answer requirement")
    return max(
        eligible,
        key=lambda result: (
            result.answerable_accepted,
            result.no_answer_abstained,
            -result.threshold,
        ),
    )


def validate_holdout_provenance(
    selection: dict[str, Any], *, dataset_sha256: str, knowledge_sha256: str
) -> None:
    if selection.get("dataset_sha256") != dataset_sha256:
        raise ValueError("dataset SHA does not match frozen selection")
    if selection.get("knowledge_manifest_sha256") != knowledge_sha256:
        raise ValueError("knowledge manifest SHA does not match frozen selection")
    if not selection.get("strategy"):
        raise ValueError("selected strategy is absent")
    if selection.get("calibrated_threshold") is None:
        raise ValueError("calibrated threshold is absent")


__all__ = [
    "CalibrationError",
    "CalibrationResult",
    "FrozenRetrievalParameters",
    "RetrievalRun",
    "RetrievalStrategy",
    "SelectionDecision",
    "StrategyMetrics",
    "calibrate_threshold",
    "retrieve_frozen_strategy",
    "score_retrieval_cases",
    "select_strategy",
    "validate_holdout_provenance",
]
