"""Stable JSON/JSONL/CSV report contracts."""

import json
from pathlib import Path
from uuid import uuid4

from verbaops.evaluation.models import (
    CaseEvaluationResult,
    EvaluationSummary,
    ExpectedOutcome,
    MetricValue,
)
from verbaops.evaluation.reports import write_artifacts


def summary() -> EvaluationSummary:
    return EvaluationSummary(
        run_id=uuid4(),
        dataset_version="text-agent-v0.1",
        dataset_sha256="a" * 64,
        case_count=2,
        overall_metrics={
            "overall_case_pass_rate": MetricValue(status="available", numerator=1, denominator=2)
        },
        prompt_version="text-agent-system-v1",
        graph_version="text-agent-v1",
        tool_schema_version="commerce-read-tools-v1",
        capability_alias="deterministic-fixture",
        failure_count=1,
    )


def result(case_id: str, passed: bool) -> CaseEvaluationResult:
    metric = MetricValue(status="available", numerator=int(passed), denominator=1)
    return CaseEvaluationResult(
        case_id=case_id,
        split="dev",
        category="order-status",
        language="en",
        passed=passed,
        expected_tool=None,
        observed_tools=(),
        expected_arguments={},
        observed_arguments={},
        expected_outcome=ExpectedOutcome(kind="benign_response"),
        observed_outcome={},
        metric_details={"task_completion": metric},
        failure_reasons=() if passed else ("task_completion",),
    )


def test_write_artifacts_has_stable_files_and_failed_only_csv(tmp_path: Path) -> None:
    run_id = summary().run_id
    artifact_dir = write_artifacts(
        run_id, summary(), (result("pass", True), result("fail", False)), tmp_path
    )
    summary_json = json.loads((artifact_dir / "summary.json").read_text(encoding="utf-8"))
    results = (artifact_dir / "results.jsonl").read_text(encoding="utf-8").splitlines()
    failed_csv = (artifact_dir / "failed_cases.csv").read_text(encoding="utf-8")
    assert summary_json["dataset_version"] == "text-agent-v0.1"
    assert len(results) == 2
    assert "fail" in failed_csv
    assert "pass" not in failed_csv
    assert "api_key" not in (artifact_dir / "summary.json").read_text(encoding="utf-8")
