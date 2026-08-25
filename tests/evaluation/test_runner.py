"""Deterministic runner and adapter contracts."""

import json
from pathlib import Path

import pytest

from verbaops.evaluation.cases import load_cases
from verbaops.evaluation.corpus import load_manifest
from verbaops.evaluation.runner import DeterministicFixtureAdapter, run_evaluation

ROOT = Path(__file__).parents[2]


@pytest.mark.asyncio
async def test_deterministic_runner_scores_representative_fixture_without_provider(
    tmp_path: Path,
) -> None:
    cases = load_cases(ROOT / "evals/agent/v0.1/cases.jsonl")[:3]
    manifest = load_manifest(ROOT / "evals/agent/v0.1/manifest.json")
    manifest = manifest.model_copy(
        update={
            "expected_case_count": 3,
            "split_counts": {"dev": 3, "release_holdout": 0},
            "category_counts": {
                "order-status": 3,
                "shipment-status": 0,
                "refund-status": 0,
                "product-search": 0,
                "delivery-slots": 0,
                "missing-ambiguous-identifiers": 0,
                "unsupported-write": 0,
                "safety-injection-identity-cross-customer": 0,
                "benign-no-tool": 0,
            },
        }
    )
    scenario_manifest = json.loads(
        (ROOT / "tests/acceptance/fixtures/novacommerce-scenarios.json").read_text()
    )
    summary = await run_evaluation(
        cases,
        DeterministicFixtureAdapter(),
        manifest=manifest,
        scenario_manifest=scenario_manifest,
        dataset_bytes=(ROOT / "evals/agent/v0.1/cases.jsonl").read_bytes(),
        output_root=tmp_path,
    )
    assert summary.case_count == 3
    assert summary.model is None
    assert summary.provider is None
    artifact_dir = tmp_path / str(summary.run_id)
    assert (artifact_dir / "summary.json").exists()
    assert (artifact_dir / "results.jsonl").exists()
    assert (artifact_dir / "failed_cases.csv").exists()


@pytest.mark.asyncio
async def test_full_corpus_is_audited_before_adapter_execution() -> None:
    cases = load_cases(ROOT / "evals/agent/v0.1/cases.jsonl")
    manifest = load_manifest(ROOT / "evals/agent/v0.1/manifest.json")
    scenario_manifest = json.loads(
        (ROOT / "tests/acceptance/fixtures/novacommerce-scenarios.json").read_text()
    )
    summary = await run_evaluation(
        cases,
        DeterministicFixtureAdapter(),
        manifest=manifest,
        scenario_manifest=scenario_manifest,
        dataset_bytes=(ROOT / "evals/agent/v0.1/cases.jsonl").read_bytes(),
        output_root=ROOT / "artifacts" / "eval_runs" / "test-runner-temporary",
    )
    assert summary.case_count == 120
