"""Deterministic baseline comparison tests."""

from uuid import uuid4

from verbaops.evaluation.baseline import BaselineArtifact
from verbaops.evaluation.compare import compare_artifacts, render_comparison
from verbaops.evaluation.models import EvaluationSummary, MetricValue

from .test_baseline import _valid_artifact


def _candidate(baseline: BaselineArtifact) -> EvaluationSummary:
    metrics = dict(baseline.overall_metrics)
    metrics["overall_case_pass_rate"] = MetricValue(
        status="available", numerator=100, denominator=120
    )
    metrics["unauthorized_action_rate"] = MetricValue(
        status="available", numerator=1, denominator=120
    )
    return EvaluationSummary(
        run_id=uuid4(),
        dataset_version=baseline.dataset_version,
        dataset_sha256=baseline.dataset_sha256,
        case_count=baseline.case_count,
        split_metrics=baseline.split_metrics,
        category_metrics=baseline.category_metrics,
        overall_metrics=metrics,
        prompt_version=baseline.prompt_version,
        graph_version=baseline.graph_version,
        tool_schema_version=baseline.tool_schema_version,
        capability_alias="candidate",
        gateway_model_id="candidate-model",
        model="candidate-model",
        provider="candidate-provider",
        latency_p50_ms=(baseline.latency_p50_ms or 0) + 10,
        latency_p95_ms=(baseline.latency_p95_ms or 0) + 20,
        total_cost_usd=(baseline.total_cost_usd or 0) + 1,
        mean_cost_usd=(baseline.mean_cost_usd or 0) + 0.01,
        failure_count=20,
    )


def test_compare_reports_higher_and_lower_is_better_deltas() -> None:
    baseline = _valid_artifact()
    rows = compare_artifacts(baseline, _candidate(baseline))
    by_name = {row.metric_name: row for row in rows}

    assert by_name["overall_case_pass_rate"].direction == "higher_is_better"
    assert by_name["overall_case_pass_rate"].delta is not None
    assert by_name["unauthorized_action_rate"].direction == "lower_is_better"
    assert by_name["latency_p95_ms"].direction == "lower_is_better"
    assert by_name["total_cost_usd"].direction == "lower_is_better"
    assert by_name["critical_safety_violation_rate"].safety is True


def test_compare_keeps_not_applicable_values_as_na_and_has_no_composite_winner() -> None:
    baseline = _valid_artifact().model_copy(update={"total_cost_usd": None, "mean_cost_usd": None})
    candidate = _candidate(baseline).model_copy(
        update={"total_cost_usd": None, "mean_cost_usd": None}
    )
    rendered = render_comparison(compare_artifacts(baseline, candidate))

    assert "N/A" in rendered
    assert "winner" not in rendered.casefold()
    assert "critical_safety_violation_rate" in rendered
