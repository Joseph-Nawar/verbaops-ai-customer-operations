"""Provider-free recovery and finalization tests."""

from pathlib import Path
from uuid import uuid4

import pytest

from verbaops.evaluation import finalization
from verbaops.evaluation.baseline import EXPECTED_DATASET_SHA256
from verbaops.evaluation.cases import load_cases
from verbaops.evaluation.metrics import aggregate_results, score_case
from verbaops.evaluation.models import (
    CaseEvaluationResult,
    EvaluationObservation,
    EvaluationSummary,
)
from verbaops.evaluation.runner import DeterministicFixtureAdapter

ROOT = Path(__file__).parents[2]


def _completed_evidence() -> tuple[EvaluationSummary, tuple[CaseEvaluationResult, ...]]:
    import asyncio

    cases = load_cases(ROOT / "evals/agent/v0.1/cases.jsonl")

    async def observe() -> tuple[EvaluationObservation, ...]:
        adapter = DeterministicFixtureAdapter()
        return tuple([await adapter.observe(case) for case in cases])

    observations = asyncio.run(observe())
    results = tuple(
        score_case(case, observation) for case, observation in zip(cases, observations, strict=True)
    )
    summary = aggregate_results(results, observations).model_copy(
        update={
            "run_id": uuid4(),
            "dataset_sha256": EXPECTED_DATASET_SHA256,
            "capability_alias": "agent-fast",
            "gateway_model_id": "groq/gpt-oss-120b",
            "model": "groq/openai/gpt-oss-120b",
            "provider": None,
        }
    )
    return summary, results


def test_completed_recovery_finalizes_without_provider_and_preserves_identity(
    tmp_path: Path,
) -> None:
    summary, results = _completed_evidence()
    bundle = finalization.write_recovery_bundle(
        tmp_path / "recovery", summary, results, "execution-sha"
    )
    finalization.finalize_recovery_bundle(
        bundle, tmp_path / "baseline.json", tmp_path / "baseline.md"
    )

    run_id, execution_sha, loaded_summary, loaded_results = finalization.load_recovery_bundle(
        bundle
    )
    assert run_id == summary.run_id
    assert execution_sha == "execution-sha"
    assert loaded_summary.run_id == summary.run_id
    assert len(loaded_results) == 120
    assert {result.case_id for result in loaded_results} == {result.case_id for result in results}


def test_reporting_failure_can_resume_without_provider_or_duplicate_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary, results = _completed_evidence()
    original_writer = finalization.write_baseline_artifacts
    bundle = finalization.write_recovery_bundle(
        tmp_path / "recovery", summary, results, "execution-sha"
    )
    calls = 0

    def fail_once(*args: object, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("synthetic reporting failure")

    monkeypatch.setattr(finalization, "write_baseline_artifacts", fail_once)
    with pytest.raises(RuntimeError, match="synthetic reporting failure"):
        finalization.finalize_recovery_bundle(
            bundle, tmp_path / "baseline.json", tmp_path / "baseline.md"
        )
    assert calls == 1
    assert (bundle / "run.json").is_file()
    assert len((bundle / "results.jsonl").read_text(encoding="utf-8").splitlines()) == 120

    monkeypatch.setattr(finalization, "write_baseline_artifacts", original_writer)
    finalization.finalize_recovery_bundle(
        bundle, tmp_path / "baseline.json", tmp_path / "baseline.md"
    )
    resumed_id, _, _, resumed_results = finalization.load_recovery_bundle(bundle)
    assert resumed_id == summary.run_id
    assert len(resumed_results) == 120
    assert len({result.case_id for result in resumed_results}) == 120


def test_recovery_bundle_rejects_known_secret_material(tmp_path: Path) -> None:
    summary, results = _completed_evidence()
    with pytest.raises(ValueError, match="secret material"):
        finalization.write_recovery_bundle(
            tmp_path / "recovery",
            summary.model_copy(update={"model": "synthetic-model"}),
            results,
            "execution-sha",
            secret_values=("synthetic-model",),
        )


def test_rescore_safety_uses_exact_allowlist_and_preserves_run_evidence() -> None:
    summary, results = _completed_evidence()
    original = results[0]
    flagged = original.model_copy(
        update={
            "observed_tools": ("get_refund_status",),
            "observed_outcome": {
                **original.observed_outcome,
                "safety": {
                    "severity": "S4",
                    "unauthorized_action": True,
                    "cross_customer_disclosure": False,
                    "identity_override": False,
                    "secret_leakage": False,
                },
            },
            "metric_details": {
                **original.metric_details,
                "unauthorized_action": {
                    "status": "available",
                    "numerator": 1,
                    "denominator": 1,
                    "value": 1.0,
                },
                "critical_safety": {
                    "status": "available",
                    "numerator": 1,
                    "denominator": 1,
                    "value": 1.0,
                },
            },
            "failure_reasons": ("unauthorized_action", "critical_safety"),
            "passed": False,
        }
    )
    corrected_summary, corrected_results = finalization.rescore_safety_results(
        summary, (flagged, *results[1:])
    )

    corrected = corrected_results[0]
    assert corrected_summary.run_id == summary.run_id
    assert len(corrected_results) == 120
    assert corrected.observed_tools == ("get_refund_status",)
    assert corrected.observed_outcome["safety"] == {
        "severity": "S0",
        "unauthorized_action": False,
        "cross_customer_disclosure": False,
        "identity_override": False,
        "secret_leakage": False,
    }
    assert corrected.metric_details["unauthorized_action"].numerator == 0
    assert corrected.metric_details["critical_safety"].numerator == 0
    assert corrected.failure_reasons == ()
    assert corrected.passed is True
    assert corrected_summary.overall_metrics["unauthorized_action_rate"].numerator == 0
    assert corrected_summary.overall_metrics["critical_safety_violation_rate"].numerator == 0
