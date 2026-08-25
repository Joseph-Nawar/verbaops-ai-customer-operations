"""Rehearse the complete provider-free Stage 4 finalization lifecycle."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from uuid import UUID

from verbaops.evaluation import finalization
from verbaops.evaluation.baseline import validate_baseline_artifact
from verbaops.evaluation.cases import load_cases
from verbaops.evaluation.compare import compare_artifacts, render_comparison
from verbaops.evaluation.metrics import aggregate_results, score_case
from verbaops.evaluation.models import (
    CaseEvaluationResult,
    EvaluationObservation,
    EvaluationSummary,
)
from verbaops.evaluation.runner import DeterministicFixtureAdapter

ROOT = Path(__file__).resolve().parents[1]
CASES_FILE = ROOT / "evals/agent/v0.1/cases.jsonl"


def _evidence(run_id: UUID) -> tuple[EvaluationSummary, tuple[CaseEvaluationResult, ...]]:
    cases = load_cases(CASES_FILE)

    async def observe() -> tuple[EvaluationObservation, ...]:
        adapter = DeterministicFixtureAdapter()
        return tuple([await adapter.observe(case) for case in cases])

    observations = asyncio.run(observe())
    results = tuple(
        score_case(case, observation) for case, observation in zip(cases, observations, strict=True)
    )
    summary = aggregate_results(results, observations).model_copy(
        update={
            "run_id": run_id,
            "dataset_sha256": "42fc86362e8e85bbe5ef4cf9d145ba0966f7616415981c28c5a2bd5449ef5367",
            "capability_alias": "agent-fast",
            "gateway_model_id": "groq/gpt-oss-120b",
            "model": "groq/openai/gpt-oss-120b",
            "provider": None,
        }
    )
    return summary, results


def main() -> int:
    run_id = UUID("11111111-1111-4111-8111-111111111111")
    with tempfile.TemporaryDirectory(prefix="verbaops-finalization-rehearsal-") as raw_dir:
        root = Path(raw_dir)
        summary, results = _evidence(run_id)
        assert len(results) == 120
        assert len({result.case_id for result in results}) == 120
        bundle = finalization.write_recovery_bundle(
            root / "artifacts" / "eval_runs" / str(run_id) / "recovery",
            summary,
            results,
            "rehearsal-execution-sha",
            runtime_metadata={
                "port": "0",
                "base_url": "https://api.groq.com/openai/v1",
                "provider": "Groq",
                "model": "groq/openai/gpt-oss-120b",
            },
        )
        baseline_json = root / "baseline.json"
        baseline_markdown = root / "baseline.md"
        original_writer = finalization.write_baseline_artifacts

        def synthetic_reporting_failure(*args: object, **kwargs: object) -> None:
            raise RuntimeError("synthetic post-run reporting failure")

        finalization.write_baseline_artifacts = synthetic_reporting_failure
        try:
            try:
                finalization.finalize_recovery_bundle(bundle, baseline_json, baseline_markdown)
            except RuntimeError as error:
                assert str(error) == "synthetic post-run reporting failure"
        finally:
            finalization.write_baseline_artifacts = original_writer

        assert (bundle / "run.json").is_file()
        assert len((bundle / "results.jsonl").read_text(encoding="utf-8").splitlines()) == 120
        finalized = finalization.finalize_recovery_bundle(bundle, baseline_json, baseline_markdown)
        promoted = validate_baseline_artifact(json.loads(baseline_json.read_text(encoding="utf-8")))
        assert finalized.run_id == run_id
        assert promoted.case_count == 120
        assert promoted.execution_git_sha == "rehearsal-execution-sha"

        candidate_path = root / "candidate.json"
        candidate_path.write_text(json.dumps(summary.model_dump(mode="json")), encoding="utf-8")
        comparison = render_comparison(
            compare_artifacts(
                promoted,
                EvaluationSummary.model_validate(json.loads(candidate_path.read_text())),
            )
        )
        assert comparison
        assert len({result.case_id for result in results}) == 120

        cleanup_marker = root / "cleanup-complete"
        assert bundle.is_dir() and baseline_json.is_file() and baseline_markdown.is_file()
        cleanup_marker.write_text("only-after-promotion\n", encoding="utf-8")
        assert cleanup_marker.read_text(encoding="utf-8") == "only-after-promotion\n"
    print("FINALIZATION_REHEARSAL=PASS cases=120 provider_calls=0 resumed_same_run=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
