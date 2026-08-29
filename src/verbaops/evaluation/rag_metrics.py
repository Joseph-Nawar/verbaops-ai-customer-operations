"""Pure deterministic retrieval and grounded-answer metrics."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import cast

from verbaops.evaluation.rag_models import GroundednessResult, MetricResult, RagLocator


def _positive(judgments: dict[str, int]) -> set[str]:
    return {key for key, grade in judgments.items() if grade >= 1}


def recall_at_k(retrieved: Sequence[str], judgments: dict[str, int], k: int) -> float | None:
    relevant = _positive(judgments)
    if not relevant:
        return None
    return len(set(retrieved[:k]) & relevant) / len(relevant)


def mean_reciprocal_rank(retrieved: Sequence[str], judgments: dict[str, int]) -> float | None:
    if not _positive(judgments):
        return None
    for rank, locator in enumerate(retrieved, 1):
        if judgments.get(locator, 0) >= 1:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(retrieved: Sequence[str], judgments: dict[str, int], k: int) -> float | None:
    if not _positive(judgments):
        return None

    def dcg(items: Iterable[str]) -> float:
        total = 0.0
        for rank, locator in enumerate(items, 1):
            total += (2 ** judgments.get(locator, 0) - 1) / math.log2(rank + 1)
        return total

    actual = dcg(retrieved[:k])
    ideal = dcg(sorted(judgments, key=lambda locator: (-judgments[locator], locator))[:k])
    return float(actual / ideal) if ideal else 0.0


def macro_mean(values: Sequence[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return sum(present) / len(present) if present else None


def citation_precision(
    citations: Sequence[str | RagLocator], judgments: dict[str, int]
) -> MetricResult:
    keys = [_locator_key(citation) for citation in citations]
    numerator = sum(judgments.get(key, 0) >= 1 for key in keys)
    denominator = len(keys)
    return MetricResult(
        numerator=numerator,
        denominator=denominator,
        value=(numerator / denominator if denominator else None),
    )


def _locator_key(locator: str | RagLocator) -> str:
    if isinstance(locator, str):
        return locator
    return f"{locator.document_slug}|{locator.document_version}|{locator.section}|{locator.chunk_index}"


def grounded_fact_score(
    answer: str,
    expected_facts: Sequence[dict[str, object]],
    cited_locators: Sequence[str | RagLocator],
) -> GroundednessResult:
    cited = {_locator_key(locator) for locator in cited_locators}
    recognized = 0
    supported = 0
    normalized_answer = " ".join(answer.casefold().split())
    for fact in expected_facts:
        aliases = [
            str(alias).casefold() for alias in cast(Sequence[object], fact.get("aliases", ()))
        ]
        if not aliases or not any(alias in normalized_answer for alias in aliases):
            continue
        recognized += 1
        support = {
            _locator_key(locator)
            for locator in cast(Sequence[str | RagLocator], fact.get("supporting_locators", ()))
        }
        supported += int(bool(cited & support))
    return GroundednessResult(
        recognized=recognized, supported=supported, unsupported=recognized - supported
    )


def unsupported_claim_rate(result: GroundednessResult) -> float | None:
    return result.unsupported / result.recognized if result.recognized else None


__all__ = [
    "citation_precision",
    "grounded_fact_score",
    "macro_mean",
    "mean_reciprocal_rank",
    "ndcg_at_k",
    "recall_at_k",
    "unsupported_claim_rate",
]
