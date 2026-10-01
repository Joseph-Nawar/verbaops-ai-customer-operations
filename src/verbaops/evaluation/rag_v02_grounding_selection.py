"""Frozen rag-v0.2 grounding quality gates and deterministic tie selection."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

GROUNDING_COMPLEXITY = {
    "P0_CURRENT": 1,
    "P1_PROMPT_V3": 2,
    "P2_FAIL_CLOSED_CITATIONS": 3,
    "P3_ONE_REPAIR_THEN_FAIL_CLOSED": 4,
}


def _value(report: Mapping[str, Any], metric_name: str) -> float | None:
    metric = report.get(metric_name)
    raw = metric.get("value") if isinstance(metric, Mapping) else metric
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    value = float(raw)
    return value if math.isfinite(value) else None


def meets_m5d_grounding_quality_gate(report: Mapping[str, Any]) -> bool:
    """Require every preregistered grounding floor with citation coverage present."""

    citation = report.get("citation_precision")
    if not isinstance(citation, Mapping) or citation.get("denominator", 0) <= 0:
        return False
    citation_precision = _value(report, "citation_precision")
    groundedness = _value(report, "groundedness")
    unsupported = _value(report, "unsupported_claim_rate")
    coverage = _value(report, "expected_fact_coverage")
    return bool(
        citation_precision is not None
        and citation_precision >= 0.95
        and groundedness is not None
        and groundedness >= 0.90
        and unsupported is not None
        and unsupported <= 0.10
        and coverage is not None
        and coverage >= 0.70
    )


def select_grounding_candidate(
    reports: Mapping[str, Mapping[str, Any]],
) -> str | None:
    """Apply the preregistered quality gates and lexicographic tie bands."""

    eligible = {
        candidate: report
        for candidate, report in reports.items()
        if candidate in GROUNDING_COMPLEXITY and meets_m5d_grounding_quality_gate(report)
    }
    if not eligible:
        return None

    def keep_within(metric: str, band: float, *, maximize: bool) -> None:
        nonlocal eligible
        values = {name: _value(report, metric) for name, report in eligible.items()}
        finite_values = {name: value for name, value in values.items() if value is not None}
        if not finite_values:
            return
        best = max(finite_values.values()) if maximize else min(finite_values.values())
        eligible = {
            name: report
            for name, report in eligible.items()
            if name in finite_values
            and (best - finite_values[name] if maximize else finite_values[name] - best)
            <= band + 1e-12
        }

    keep_within("citation_precision", 0.01, maximize=True)
    keep_within("groundedness", 0.01, maximize=True)
    keep_within("unsupported_claim_rate", 0.01, maximize=False)
    keep_within("expected_fact_coverage", 0.02, maximize=True)

    def final_key(candidate: str) -> tuple[float, float, int, str]:
        report = eligible[candidate]
        latency = _value(report, "answer_latency_p95_ms")
        cost = _value(report, "mean_cost_usd_over_costed_observations")
        return (
            latency if latency is not None else math.inf,
            cost if cost is not None else math.inf,
            GROUNDING_COMPLEXITY[candidate],
            candidate,
        )

    return min(eligible, key=final_key)


__all__ = ["GROUNDING_COMPLEXITY", "meets_m5d_grounding_quality_gate", "select_grounding_candidate"]
