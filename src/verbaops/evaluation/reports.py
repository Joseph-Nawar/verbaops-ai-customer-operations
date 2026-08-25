"""Stable local artifact and console report generation."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from uuid import UUID

from verbaops.evaluation.models import CaseEvaluationResult, EvaluationSummary, MetricValue


def _metric_text(metric: MetricValue | None) -> str:
    if metric is None or metric.status == "not_applicable":
        return "N/A"
    return f"{metric.value:.2%} ({metric.numerator}/{metric.denominator})"


def write_artifacts(
    run_id: UUID,
    summary: EvaluationSummary,
    results: tuple[CaseEvaluationResult, ...],
    output_root: Path,
) -> Path:
    """Write the stable summary, results JSONL, and failed-case CSV files."""

    artifact_dir = output_root / str(run_id)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "summary.json").write_text(
        json.dumps(summary.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    with (artifact_dir / "results.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for result in results:
            handle.write(json.dumps(result.model_dump(mode="json"), ensure_ascii=False) + "\n")
    with (artifact_dir / "failed_cases.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "case_id",
                "split",
                "category",
                "expected_tool",
                "observed_tools",
                "failure_reasons",
            ),
        )
        writer.writeheader()
        for result in results:
            if not result.passed:
                writer.writerow(
                    {
                        "case_id": result.case_id,
                        "split": result.split,
                        "category": result.category,
                        "expected_tool": result.expected_tool or "",
                        "observed_tools": ",".join(result.observed_tools),
                        "failure_reasons": ";".join(result.failure_reasons),
                    }
                )
    return artifact_dir


def render_console_summary(summary: EvaluationSummary, artifact_dir: Path) -> str:
    """Render the compact operator-facing evaluation summary."""

    metrics = summary.overall_metrics
    lines = [
        "VerbaOps Text Agent Evaluation v0.1",
        f"Dataset: {summary.dataset_version}",
        f"Cases: {summary.case_count}",
        "",
        f"Overall case pass: {_metric_text(metrics.get('overall_case_pass_rate'))}",
        f"Tool selection: {_metric_text(metrics.get('tool_selection_accuracy'))}",
        f"Arguments field accuracy: {_metric_text(metrics.get('argument_field_accuracy'))}",
        f"Arguments all-fields accuracy: {_metric_text(metrics.get('argument_all_fields_accuracy'))}",
        f"Task completion: {_metric_text(metrics.get('task_completion_rate'))}",
        f"Clarification: {_metric_text(metrics.get('clarification_accuracy'))}",
        f"Unnecessary tool calls: {_metric_text(metrics.get('unnecessary_tool_call_rate'))}",
        f"Unauthorized actions: {_metric_text(metrics.get('unauthorized_action_rate'))}",
        f"S4 violations: {_metric_text(metrics.get('critical_safety_violation_rate'))}",
        f"Latency p50/p95: {summary.latency_p50_ms if summary.latency_p50_ms is not None else 'N/A'}/{summary.latency_p95_ms if summary.latency_p95_ms is not None else 'N/A'} ms",
        f"Cost: {summary.total_cost_usd if summary.total_cost_usd is not None else 'N/A'} USD",
        "",
        f"Failures: {summary.failure_count}",
        f"Artifacts: {artifact_dir}",
    ]
    return "\n".join(lines)
