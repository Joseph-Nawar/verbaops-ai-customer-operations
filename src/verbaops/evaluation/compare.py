"""Deterministic, metric-by-metric comparison of evaluation artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from verbaops.evaluation.baseline import BaselineArtifact
from verbaops.evaluation.models import EvaluationSummary, MetricValue

Direction = Literal["higher_is_better", "lower_is_better"]


@dataclass(frozen=True, slots=True)
class ComparisonRow:
    """One independently interpretable baseline/candidate metric row."""

    metric_name: str
    direction: Direction
    baseline: float | None
    candidate: float | None
    delta: float | None
    safety: bool = False


_METRIC_DIRECTIONS: tuple[tuple[str, Direction, bool], ...] = (
    ("overall_case_pass_rate", "higher_is_better", False),
    ("tool_selection_accuracy", "higher_is_better", False),
    ("argument_field_accuracy", "higher_is_better", False),
    ("argument_all_fields_accuracy", "higher_is_better", False),
    ("task_completion_rate", "higher_is_better", False),
    ("unauthorized_action_rate", "lower_is_better", True),
    ("unnecessary_tool_call_rate", "lower_is_better", False),
    ("clarification_accuracy", "higher_is_better", False),
    ("critical_safety_violation_rate", "lower_is_better", True),
)


def _metric_value(metric: MetricValue | None) -> float | None:
    return None if metric is None or metric.status == "not_applicable" else metric.value


def _delta(baseline: float | None, candidate: float | None) -> float | None:
    if baseline is None or candidate is None:
        return None
    return round(candidate - baseline, 12)


def compare_artifacts(
    baseline: BaselineArtifact, candidate: EvaluationSummary
) -> tuple[ComparisonRow, ...]:
    """Compare every required quality, safety, latency, and cost metric."""

    rows: list[ComparisonRow] = []
    for name, direction, safety in _METRIC_DIRECTIONS:
        baseline_value = _metric_value(baseline.overall_metrics.get(name))
        candidate_value = _metric_value(candidate.overall_metrics.get(name))
        rows.append(
            ComparisonRow(
                metric_name=name,
                direction=direction,
                baseline=baseline_value,
                candidate=candidate_value,
                delta=_delta(baseline_value, candidate_value),
                safety=safety,
            )
        )
    for name, direction, baseline_value, candidate_value in (
        ("latency_p50_ms", "lower_is_better", baseline.latency_p50_ms, candidate.latency_p50_ms),
        ("latency_p95_ms", "lower_is_better", baseline.latency_p95_ms, candidate.latency_p95_ms),
        ("total_cost_usd", "lower_is_better", baseline.total_cost_usd, candidate.total_cost_usd),
        ("mean_cost_usd", "lower_is_better", baseline.mean_cost_usd, candidate.mean_cost_usd),
    ):
        rows.append(
            ComparisonRow(
                metric_name=name,
                direction=direction,
                baseline=baseline_value,
                candidate=candidate_value,
                delta=_delta(baseline_value, candidate_value),
                safety=False,
            )
        )
    return tuple(rows)


def _display(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.6f}"


def render_comparison(rows: tuple[ComparisonRow, ...]) -> str:
    """Render rows without collapsing independent metrics into a winner."""

    lines = [
        "VerbaOps evaluation comparison",
        "",
        "| Metric | Direction | Baseline | Candidate | Delta | Safety |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            f"| `{row.metric_name}` | {row.direction} | {_display(row.baseline)} | "
            f"{_display(row.candidate)} | {_display(row.delta)} | "
            f"{'yes' if row.safety else 'no'} |"
        )
    return "\n".join(lines) + "\n"
