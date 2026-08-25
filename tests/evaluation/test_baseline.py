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
    contains_secret_material,
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


@pytest.mark.parametrize(
    "safe_value",
    [
        "0",
        "5432",
        "https://api.groq.com/openai/v1",
        "groq/openai/gpt-oss-120b",
        "Groq",
    ],
)
def test_nonsecret_runtime_values_do_not_trigger_secret_scan(
    tmp_path: Path, safe_value: str
) -> None:
    artifact = _valid_artifact().model_copy(update={"model": safe_value})
    write_baseline_artifacts(
        artifact,
        tmp_path / "safe.json",
        tmp_path / "safe.md",
    )


@pytest.mark.parametrize("output_kind", ["json", "markdown"])
def test_sensitive_synthetic_api_key_is_rejected_in_each_output_kind(
    tmp_path: Path, output_kind: str
) -> None:
    synthetic_key = "sk-synthetic-api-key-1234567890"
    artifact = _valid_artifact().model_copy(update={"model": synthetic_key})
    with pytest.raises(ValueError, match="secret material"):
        write_baseline_artifacts(
            artifact,
            tmp_path / f"{output_kind}.json",
            tmp_path / f"{output_kind}.md",
            secret_values=(synthetic_key,),
        )


def test_sensitive_synthetic_master_key_is_rejected_in_json_and_markdown(
    tmp_path: Path,
) -> None:
    synthetic_master_key = "sk-master-synthetic-1234567890"
    artifact = _valid_artifact().model_copy(update={"execution_git_sha": synthetic_master_key})
    with pytest.raises(ValueError, match="secret material"):
        write_baseline_artifacts(
            artifact,
            tmp_path / "master.json",
            tmp_path / "master.md",
            secret_values=(synthetic_master_key,),
        )


def test_secret_scanner_checks_json_and_markdown_content() -> None:
    synthetic_key = "sk-synthetic-json-markdown-1234567890"
    assert contains_secret_material({"model": synthetic_key}, (synthetic_key,))
    assert contains_secret_material(f"model: `{synthetic_key}`", (synthetic_key,))
