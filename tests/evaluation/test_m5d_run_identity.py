from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from verbaops.evaluation.m5d_run_identity import (
    artifact_reference,
    bind_checkpoint_identity,
    load_checkpoint_records,
    require_canonical_run_directory,
    require_committed_behavior,
    validate_dev_decision_provenance,
    verify_artifact_references,
)


def _identity() -> dict[str, Any]:
    return {
        "benchmark_version": "rag-v0.2",
        "split": "dev",
        "dataset_sha256": "a" * 64,
        "knowledge_manifest_sha256": "b" * 64,
        "experiment_plan_sha256": "c" * 64,
        "pre_experiment_sha": "d" * 40,
        "evaluated_git_sha": "e" * 40,
        "evidence_gate": "G2_TOP_EVIDENCE_CROSS_ENCODER",
        "evidence_gate_threshold": 0.25,
        "grounding_candidate": "P0_CURRENT",
        "model_candidate": "M0",
        "retrieval_profile_version": "knowledge-retrieval-v1.1",
        "agent_prompt_version": "system_v2",
        "agent_graph_version": "agent-graph-v2",
        "model_revision": "groq/openai/gpt-oss-120b",
        "run_id": "canonical-run-001",
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("evidence_gate", "G0_CURRENT_RRF"),
        ("evidence_gate_threshold", 0.3),
        ("grounding_candidate", "P1_PROMPT_V3"),
        ("model_candidate", "M1"),
        ("dataset_sha256", "f" * 64),
        ("knowledge_manifest_sha256", "0" * 64),
        ("experiment_plan_sha256", "1" * 64),
        ("evaluated_git_sha", "2" * 40),
        ("run_id", "different-run"),
    ],
)
def test_checkpoint_identity_rejects_incompatible_resume(
    field: str, value: object, tmp_path: Path
) -> None:
    checkpoint = tmp_path / "cases.jsonl"
    identity = _identity()
    bind_checkpoint_identity(checkpoint, identity)

    changed = {**identity, field: value}
    with pytest.raises(ValueError, match="identity mismatch"):
        bind_checkpoint_identity(checkpoint, changed)


def test_checkpoint_resume_rejects_corrupt_and_duplicate_records(tmp_path: Path) -> None:
    checkpoint = tmp_path / "cases.jsonl"
    identity = _identity()
    fingerprint = bind_checkpoint_identity(checkpoint, identity)
    valid = {
        "case_id": "case-1",
        "run_id": identity["run_id"],
        "run_identity_sha256": fingerprint,
    }
    checkpoint.write_text(json.dumps(valid) + "\n" + json.dumps(valid) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate"):
        load_checkpoint_records(checkpoint, identity, expected_case_ids={"case-1"})

    checkpoint.write_text("{not-json}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid"):
        load_checkpoint_records(checkpoint, identity, expected_case_ids={"case-1"})

    checkpoint.write_text(json.dumps(valid) + "\n", encoding="utf-8")
    checkpoint.with_name(f"{checkpoint.name}.identity.json").unlink()
    with pytest.raises(ValueError, match="no bound run identity"):
        load_checkpoint_records(checkpoint, identity, expected_case_ids={"case-1"})


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def _committed_repo(root: Path) -> None:
    root.mkdir()
    _git(root, "init", "--quiet")
    _git(root, "config", "user.email", "m5d-test@example.invalid")
    _git(root, "config", "user.name", "M5D test")
    (root / "src").mkdir()
    (root / "src" / "behavior.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(root, "add", "src/behavior.py")
    _git(root, "commit", "--quiet", "-m", "committed behavior")


def test_canonical_execution_rejects_uncommitted_behavior_changes(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _committed_repo(root)
    (root / "src" / "behavior.py").write_text("VALUE = 2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="uncommitted behavior or specification changes"):
        require_committed_behavior(root)


def test_canonical_execution_rejects_untracked_behavior_source(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _committed_repo(root)
    (root / "src" / "new_behavior.py").write_text("VALUE = 2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="uncommitted behavior or specification changes"):
        require_committed_behavior(root)


def test_canonical_execution_requires_preregistration_commit_ancestor(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _committed_repo(root)
    current_sha = _git_sha(root)

    assert require_committed_behavior(root, pre_experiment_sha=current_sha) == current_sha

    with pytest.raises(ValueError, match="does not contain PRE_EXPERIMENT_SHA"):
        require_committed_behavior(root, pre_experiment_sha="f" * 40)


def test_canonical_run_directory_is_bound_to_its_run_id(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    path = root / "evals/rag/v0.2/dev-evidence/canonical/run-001"

    assert require_canonical_run_directory(root, path, run_id="run-001") == path.resolve()
    with pytest.raises(ValueError, match="directory must match run ID"):
        require_canonical_run_directory(root, path, run_id="run-002")


def test_expected_generated_evaluation_outputs_do_not_invalidate_execution(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    _committed_repo(root)
    generated = root / "evals/rag/v0.2/dev-evidence/canonical/run-001"
    generated.mkdir(parents=True)
    (generated / "cases.jsonl").write_text('{"case_id":"case-1"}\n', encoding="utf-8")

    assert require_committed_behavior(root) == _git_sha(root)


def test_artifact_reference_verification_rejects_changed_file(tmp_path: Path) -> None:
    artifact = tmp_path / "report.json"
    artifact.write_text("original", encoding="utf-8")
    reference = artifact_reference(tmp_path, artifact)
    verify_artifact_references(tmp_path, [reference])
    artifact.write_text("changed", encoding="utf-8")

    with pytest.raises(ValueError, match="sha256 does not match"):
        verify_artifact_references(tmp_path, [reference])


def _git_sha(root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_completed_decision_requires_hash_bound_canonical_run_provenance() -> None:
    incomplete = {"canonical_evidence_status": "COMPLETE"}
    with pytest.raises(ValueError, match="canonical provenance"):
        validate_dev_decision_provenance(incomplete)

    decision: dict[str, Any] = {
        "canonical_evidence_status": "COMPLETE",
        "pre_experiment_sha": "d" * 40,
        "evaluated_git_shas": ["e" * 40],
        "canonical_runs": [
            {
                "run_id": "canonical-run-001",
                "evaluated_git_sha": "e" * 40,
                "run_identity_sha256": "f" * 64,
                "artifacts": [
                    {"path": "evals/rag/v0.2/dev-evidence/run/report.json", "sha256": "a" * 64}
                ],
            }
        ],
    }
    validate_dev_decision_provenance(decision)

    decision["canonical_runs"][0]["artifacts"][0].pop("sha256")
    with pytest.raises(ValueError, match=r"artifact.*sha256"):
        validate_dev_decision_provenance(decision)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda run: run.pop("run_id"),
        lambda run: run.pop("evaluated_git_sha"),
        lambda run: run.pop("run_identity_sha256"),
        lambda run: run["artifacts"][0].pop("path"),
        lambda run: run["artifacts"][0].update(sha256="bad"),
    ],
    ids=["run-id", "evaluated-sha", "run-identity-sha", "artifact-path", "artifact-sha"],
)
def test_completed_decision_rejects_missing_run_or_artifact_provenance(
    mutate: Any,
) -> None:
    decision = {
        "canonical_evidence_status": "COMPLETE",
        "pre_experiment_sha": "d" * 40,
        "evaluated_git_shas": ["e" * 40],
        "canonical_runs": [
            {
                "run_id": "canonical-run-001",
                "evaluated_git_sha": "e" * 40,
                "run_identity_sha256": "f" * 64,
                "artifacts": [
                    {"path": "evals/rag/v0.2/dev-evidence/run/report.json", "sha256": "a" * 64}
                ],
            }
        ],
    }
    mutate(decision["canonical_runs"][0])

    with pytest.raises(ValueError):
        validate_dev_decision_provenance(decision)
