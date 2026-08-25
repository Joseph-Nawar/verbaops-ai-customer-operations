"""Strict provenance and serialization tests for the genuine baseline artifact."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from verbaops.agent.versions import GRAPH_VERSION, PROMPT_VERSION, TOOL_SCHEMA_VERSION
from verbaops.evaluation.baseline import (
    EXPECTED_DATASET_SHA256,
    EXPECTED_STAGE3_LOCK_SHA,
    BaselineArtifact,
    build_baseline_artifact,
    validate_baseline_artifact,
    write_baseline_artifacts,
)
from verbaops.evaluation.cases import load_cases
from verbaops.evaluation.metrics import aggregate_results, score_case
from verbaops.evaluation.models import EvaluationObservation
from verbaops.evaluation.runner import DeterministicFixtureAdapter

ROOT = Path(__file__).parents[2]


def _valid_artifact() -> BaselineArtifact:
    import asyncio

    cases = load_cases(ROOT / "evals/agent/v0.1/cases.jsonl")

    async def observations() -> tuple[EvaluationObservation, ...]:
        adapter = DeterministicFixtureAdapter()
        return tuple([await adapter.observe(case) for case in cases])

    observed = asyncio.run(observations())
    results = tuple(
        score_case(case, observation) for case, observation in zip(cases, observed, strict=True)
    )
    summary = aggregate_results(results, observed).model_copy(
        update={
            "dataset_sha256": EXPECTED_DATASET_SHA256,
            "capability_alias": "agent-fast",
            "gateway_model_id": "provider-model",
            "model": "provider-model",
            "provider": "provider",
        }
    )
    return build_baseline_artifact(
        summary,
        results,
        execution_git_sha="execution-sha",
        timestamp=datetime(2026, 8, 25, tzinfo=UTC),
    )


def test_build_baseline_artifact_records_exact_provenance_and_splits() -> None:
    artifact = _valid_artifact()

    assert artifact.dataset_sha256 == EXPECTED_DATASET_SHA256
    assert artifact.stage3_lock_sha == EXPECTED_STAGE3_LOCK_SHA
    assert artifact.case_count == 120
    assert artifact.split_counts == {"dev": 96, "release_holdout": 24}
    assert sum(artifact.category_counts.values()) == 120
    assert artifact.capability_alias == "agent-fast"
    assert artifact.unauthorized_action_count == 0
    assert artifact.critical_safety_violation_count == 0
    assert validate_baseline_artifact(artifact) == artifact


@pytest.mark.parametrize(
    "change",
    [
        {"dataset_sha256": "0" * 64},
        {"case_count": 119},
        {"capability_alias": "deterministic-fixture"},
        {"split_counts": {"dev": 95, "release_holdout": 24}},
    ],
)
def test_validate_baseline_rejects_invalid_provenance(change: dict[str, object]) -> None:
    invalid = _valid_artifact().model_copy(update=change)
    with pytest.raises(ValueError):
        validate_baseline_artifact(invalid)


def test_baseline_writer_emits_machine_json_and_no_secret_material(tmp_path: Path) -> None:
    artifact = _valid_artifact()
    json_path = tmp_path / "baseline.json"
    markdown_path = tmp_path / "baseline.md"

    write_baseline_artifacts(
        artifact,
        json_path,
        markdown_path,
        secret_values=("sentinel-secret",),
    )

    serialized = json_path.read_text(encoding="utf-8") + markdown_path.read_text(encoding="utf-8")
    assert "sentinel-secret" not in serialized
    assert '"split_counts"' in serialized
    assert "release_holdout" in serialized


def test_baseline_models_preserve_not_applicable_cost() -> None:
    artifact = _valid_artifact().model_copy(update={"total_cost_usd": None, "mean_cost_usd": None})
    assert validate_baseline_artifact(artifact).total_cost_usd is None
    assert artifact.prompt_version == PROMPT_VERSION
    assert artifact.graph_version == GRAPH_VERSION
    assert artifact.tool_schema_version == TOOL_SCHEMA_VERSION
