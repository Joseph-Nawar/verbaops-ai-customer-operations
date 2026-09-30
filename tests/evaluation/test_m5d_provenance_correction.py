from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import migrate_m5d_canonical_provenance, run_m5d_grounded_eval

from verbaops.agent.evaluation import AgentEvaluationProfile, GroundingCandidate
from verbaops.evaluation import m5d_run_identity
from verbaops.evaluation.m5d_run_identity import (
    bind_checkpoint_identity,
    load_checkpoint_records,
)
from verbaops.retrieval.evidence_gate import EvidenceGate

_CANDIDATES = (
    ("P0_CURRENT", GroundingCandidate.P0_CURRENT, "text-agent-system-v2"),
    ("P1_PROMPT_V3", GroundingCandidate.P1_PROMPT_V3, "text-agent-system-v3"),
    (
        "P2_FAIL_CLOSED_CITATIONS",
        GroundingCandidate.P2_FAIL_CLOSED_CITATIONS,
        "text-agent-system-v3",
    ),
    (
        "P3_ONE_REPAIR_THEN_FAIL_CLOSED",
        GroundingCandidate.P3_ONE_REPAIR_THEN_FAIL_CLOSED,
        "text-agent-system-v3",
    ),
)


class _IdentityCaptured(Exception):
    pass


def _capture_runner_identity(
    candidate: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    captured: dict[str, Any] = {}
    gate = EvidenceGate.G2_TOP_EVIDENCE_CROSS_ENCODER
    app_sha = "e" * 40
    harness_sha = "f" * 40
    gate_identity = {
        "benchmark_version": "rag-v0.2",
        "split": "dev",
        "dataset_sha256": "a" * 64,
        "knowledge_manifest_sha256": "b" * 64,
        "experiment_plan_sha256": "c" * 64,
        "pre_experiment_sha": m5d_run_identity.PRE_EXPERIMENT_SHA,
        "evaluated_git_sha": app_sha,
        "evidence_gate": "CALIBRATE_ALL_PREREGISTERED_GATES",
        "evidence_gate_threshold": "calibration_sweep",
        "grounding_candidate": "NOT_APPLICABLE_GATE_CALIBRATION",
        "model_candidate": "NOT_APPLICABLE_GATE_CALIBRATION",
        "retrieval_profile_version": "knowledge-retrieval-v1.1",
        "agent_prompt_version": "not_applicable_gate_calibration",
        "agent_graph_version": "not_applicable_gate_calibration",
        "model_revision": "test-model",
        "run_id": "canonical-gate-test",
    }
    gate_report = {
        "run_id": gate_identity["run_id"],
        "run_identity": gate_identity,
        "run_identity_sha256": m5d_run_identity.run_identity_sha256(gate_identity),
        "evaluated_git_sha": app_sha,
        "pre_experiment_sha": m5d_run_identity.PRE_EXPERIMENT_SHA,
        "selected_gate": {"gate": gate.value, "threshold": 0.2554669},
        "holdout_executed": False,
        "artifacts": [],
    }
    gate_path = tmp_path / "gate-report.json"
    gate_path.write_text(json.dumps(gate_report), encoding="utf-8")

    monkeypatch.setattr(
        run_m5d_grounded_eval,
        "audit_rag_v02",
        lambda _root: SimpleNamespace(
            dataset_version="rag-v0.2",
            dataset_sha256="a" * 64,
            knowledge_manifest_sha256="b" * 64,
        ),
    )
    monkeypatch.setattr(
        run_m5d_grounded_eval,
        "load_rag_v02_cases",
        lambda _path: tuple(SimpleNamespace(split="dev") for _ in range(96)),
    )
    monkeypatch.setattr(run_m5d_grounded_eval, "guard_rag_v02_split", lambda _split: None)
    monkeypatch.setattr(
        run_m5d_grounded_eval,
        "require_canonical_revisions",
        lambda *_args, **_kwargs: (app_sha, harness_sha),
    )
    monkeypatch.setattr(
        run_m5d_grounded_eval,
        "require_canonical_run_directory",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(run_m5d_grounded_eval, "verify_artifact_references", lambda *_args: None)

    def capture(_checkpoint: Path, identity: dict[str, Any]) -> str:
        captured.update(identity)
        raise _IdentityCaptured

    monkeypatch.setattr(run_m5d_grounded_eval, "bind_checkpoint_identity", capture)
    args = argparse.Namespace(
        split="dev",
        database_url="postgresql+asyncpg://test",
        token="test-token",
        grounding=candidate,
        model_candidate="M0",
        gate=gate.value,
        gate_report=gate_path,
        threshold=0.2554669,
        run_dir=tmp_path / "evals/rag/v0.2/dev-evidence/canonical/test-run",
        run_id="canonical-test-run",
    )
    try:
        import asyncio

        asyncio.run(run_m5d_grounded_eval._run(args))
    except _IdentityCaptured:
        return captured
    raise AssertionError("runner did not bind its run identity")


@pytest.mark.parametrize("candidate,profile_candidate,expected_prompt", _CANDIDATES)
def test_runner_identity_versions_match_the_runtime_evaluation_profile(
    candidate: str,
    profile_candidate: GroundingCandidate,
    expected_prompt: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = _capture_runner_identity(candidate, tmp_path, monkeypatch)
    profile = AgentEvaluationProfile(
        grounding_candidate=profile_candidate,
        evidence_gate=EvidenceGate.G2_TOP_EVIDENCE_CROSS_ENCODER,
        evidence_gate_threshold=0.2554669,
        model_candidate="M0",
    )

    assert identity["agent_prompt_version"] == f"text-agent-system-{profile.prompt_version}"
    assert identity["agent_prompt_version"] == expected_prompt
    assert identity["agent_graph_version"] == profile.graph_version
    assert identity["agent_graph_version"] == "text-agent-m5d-v1"


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _repo_with_application_and_harness(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "--quiet")
    _git(root, "config", "user.email", "m5d-test@example.invalid")
    _git(root, "config", "user.name", "M5D test")
    for relative, content in (
        ("src/verbaops/agent/graph.py", "GRAPH = 'baseline'\n"),
        ("scripts/run_m5d_grounded_eval.py", "HARNESS = 'baseline'\n"),
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "--quiet", "-m", "application and harness base")
    return root, _git(root, "rev-parse", "HEAD")


def _canonical_revisions_function() -> Any:
    function = getattr(m5d_run_identity, "require_canonical_revisions", None)
    assert callable(function), "canonical application/harness revision check is missing"
    return function


def test_harness_only_commit_preserves_application_sha_and_records_harness_sha(
    tmp_path: Path,
) -> None:
    root, application_sha = _repo_with_application_and_harness(tmp_path)
    harness_file = root / "scripts/run_m5d_grounded_eval.py"
    harness_file.write_text("HARNESS = 'corrected'\n", encoding="utf-8")
    _git(root, "add", "scripts/run_m5d_grounded_eval.py")
    _git(root, "commit", "--quiet", "-m", "evaluation harness correction")
    expected_harness_sha = _git(root, "rev-parse", "HEAD")

    resolved_application_sha, resolved_harness_sha = _canonical_revisions_function()(
        root, application_sha=application_sha, pre_experiment_sha=None
    )

    assert resolved_application_sha == application_sha
    assert resolved_harness_sha == expected_harness_sha


@pytest.mark.parametrize(
    "relative_path",
    (
        "src/verbaops/agent/graph.py",
        "src/verbaops/agent/runtime.py",
        "src/verbaops/agent/prompts/system_v3.md",
        "src/verbaops/agent/tools/catalog.py",
        "src/verbaops/retrieval/service.py",
    ),
)
def test_behavior_file_change_after_application_sha_is_rejected(
    relative_path: str, tmp_path: Path
) -> None:
    root, application_sha = _repo_with_application_and_harness(tmp_path)
    changed = root / relative_path
    changed.parent.mkdir(parents=True, exist_ok=True)
    changed.write_text("behavior changed\n", encoding="utf-8")
    _git(root, "add", relative_path)
    _git(root, "commit", "--quiet", "-m", "behavior drift")

    with pytest.raises(ValueError, match="application behavior drift"):
        _canonical_revisions_function()(
            root, application_sha=application_sha, pre_experiment_sha=None
        )


def test_uncommitted_behavior_change_is_rejected_but_generated_output_is_allowed(
    tmp_path: Path,
) -> None:
    root, application_sha = _repo_with_application_and_harness(tmp_path)
    generated = root / "evals/rag/v0.2/dev-evidence/canonical/run/grounded_cases.jsonl"
    generated.parent.mkdir(parents=True)
    generated.write_text("generated evaluation output\n", encoding="utf-8")
    revisions = _canonical_revisions_function()(
        root, application_sha=application_sha, pre_experiment_sha=None
    )
    assert revisions == (application_sha, application_sha)

    _git(root, "add", "evals/rag/v0.2/dev-evidence/canonical/run/grounded_cases.jsonl")
    _git(root, "commit", "--quiet", "-m", "generated canonical evidence")
    generated.write_text("resumed evaluation output\n", encoding="utf-8")
    revisions = _canonical_revisions_function()(
        root, application_sha=application_sha, pre_experiment_sha=None
    )
    assert revisions == (application_sha, application_sha)

    prompt = root / "src/verbaops/agent/graph.py"
    prompt.write_text("GRAPH = 'uncommitted behavior change'\n", encoding="utf-8")
    with pytest.raises(ValueError, match="uncommitted behavior"):
        _canonical_revisions_function()(
            root, application_sha=application_sha, pre_experiment_sha=None
        )


def _migration_function() -> Any:
    function = getattr(m5d_run_identity, "migrate_checkpoint_provenance", None)
    assert callable(function), "explicit canonical provenance migration is missing"
    return function


def _migration_fixture_identity() -> dict[str, Any]:
    return {
        "benchmark_version": "rag-v0.2",
        "split": "dev",
        "dataset_sha256": "398521c3a2974634c7d8aace8a391fac33b10b60c3718814d4b222612168a595",
        "knowledge_manifest_sha256": "26bf94fd2fea6b0b5ce0ba0c91f87ae67dad32b95446a9ae1fa8301e21ee4660",
        "experiment_plan_sha256": "b9835dd0e7bb974480769d328f19d903cb9466828a0ac810200cc10b36251ba8",
        "pre_experiment_sha": m5d_run_identity.PRE_EXPERIMENT_SHA,
        "evaluated_git_sha": m5d_run_identity.CANONICAL_APPLICATION_SHA,
        "evidence_gate": "G2_TOP_EVIDENCE_CROSS_ENCODER",
        "evidence_gate_threshold": 0.2554669,
        "grounding_candidate": "P0_CURRENT",
        "model_candidate": "M0",
        "retrieval_profile_version": "knowledge-retrieval-v1.1",
        "agent_prompt_version": "text-agent-system-v2",
        "agent_graph_version": "text-agent-v2",
        "model_revision": "groq/openai/gpt-oss-120b",
        "run_id": "canonical-M0-P0-20260929T124811Z-0d27c8d7",
    }


def _migration_fixture(
    tmp_path: Path,
) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any]]:
    old_identity = _migration_fixture_identity()
    checkpoint = tmp_path / "grounded_cases.jsonl"
    old_fingerprint = bind_checkpoint_identity(checkpoint, old_identity)
    record = {
        "case_id": "case-1",
        "run_id": old_identity["run_id"],
        "run_identity_sha256": old_fingerprint,
        "agent_run_id": "agent-run-1",
        "evaluated_git_sha": old_identity["evaluated_git_sha"],
        "final_answer": "A substantive answer",
        "selected_evidence": ["doc|v1|section|1"],
        "public_citations": ["cite-1"],
        "model": "groq/openai/gpt-oss-120b",
        "model_call_count": 1,
        "tool_call_count": 0,
        "answer_latency_ms": 123.0,
        "cost_usd": 0.001,
        "top_confidence_score": 0.5,
        "repair_attempted": False,
        "repair_succeeded": False,
        "status": "completed",
    }
    checkpoint.write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")
    corrected_identity = {
        **old_identity,
        "agent_prompt_version": "text-agent-system-v2",
        "agent_graph_version": "text-agent-m5d-v1",
        "evaluation_harness_sha": "f" * 40,
    }
    trace = {
        "case_id": "case-1",
        "agent_run_id": "agent-run-1",
        "prompt_version": "text-agent-system-v2",
        "graph_version": "text-agent-m5d-v1",
        "status": "completed",
        "user_message": "query one",
    }
    return checkpoint, record, corrected_identity, trace


def test_provenance_migration_changes_only_checkpoint_identity_fields(tmp_path: Path) -> None:
    checkpoint, original, corrected_identity, trace = _migration_fixture(tmp_path)
    correction_artifact = tmp_path / "provenance-correction.json"

    result = _migration_function()(
        checkpoint,
        corrected_identity=corrected_identity,
        expected_case_queries={"case-1": "query one"},
        runtime_traces=[trace],
        correction_artifact_path=correction_artifact,
        harness_correction_sha="f" * 40,
        apply_canonical_provenance_correction=True,
    )

    migrated = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert {key: value for key, value in migrated.items() if key != "run_identity_sha256"} == {
        key: value for key, value in original.items() if key != "run_identity_sha256"
    }
    assert migrated["run_identity_sha256"] == result["corrected_identity_sha256"]
    assert (
        result["non_provenance_observation_sha256_before"]
        == result["non_provenance_observation_sha256_after"]
    )
    artifact = json.loads(correction_artifact.read_text(encoding="utf-8"))
    assert artifact["old_identity"]
    assert artifact["corrected_identity"] == corrected_identity
    assert artifact["verified_trace_count"] == 1


def test_report_identity_refresh_preserves_p0_metrics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(migrate_m5d_canonical_provenance, "ROOT", tmp_path)
    run_dir = tmp_path / "evals/rag/v0.2/dev-evidence/canonical/p0"
    run_dir.mkdir(parents=True)
    checkpoint = run_dir / "grounded_cases.jsonl"
    checkpoint.write_text("{}\n", encoding="utf-8")
    checkpoint.with_name(f"{checkpoint.name}.identity.json").write_text("{}\n", encoding="utf-8")
    (run_dir / "provenance-correction.json").write_text("{}\n", encoding="utf-8")
    metrics = {
        "citation_precision": {"numerator": 12, "denominator": 18, "value": 12 / 18},
        "groundedness": {"numerator": 2, "denominator": 4, "value": 0.5},
        "unsupported_claim_rate": {"numerator": 2, "denominator": 4, "value": 0.5},
        "expected_fact_coverage": {"numerator": 4, "denominator": 72, "value": 4 / 72},
    }
    report_path = run_dir / "report.json"
    report_path.write_text(
        json.dumps({**metrics, "canonical_run_identity_sha256": "a" * 64}),
        encoding="utf-8",
    )
    for filename in ("metadata.json", "run-summary.json"):
        (run_dir / filename).write_text("{}\n", encoding="utf-8")
    corrected_identity = {
        **_migration_fixture_identity(),
        "agent_graph_version": "text-agent-m5d-v1",
        "evaluation_harness_sha": "f" * 40,
    }

    migrate_m5d_canonical_provenance._refresh_run_metadata(run_dir, corrected_identity, "b" * 64)

    refreshed = json.loads(report_path.read_text(encoding="utf-8"))
    assert {key: refreshed[key] for key in metrics} == metrics
    assert refreshed["canonical_run_identity_sha256"] == "b" * 64


def test_provenance_migration_requires_matching_persisted_runtime_trace(tmp_path: Path) -> None:
    checkpoint, _record, corrected_identity, trace = _migration_fixture(tmp_path)

    with pytest.raises(ValueError, match="runtime trace"):
        _migration_function()(
            checkpoint,
            corrected_identity=corrected_identity,
            expected_case_queries={"case-1": "query one"},
            runtime_traces=[],
            correction_artifact_path=tmp_path / "provenance-correction.json",
            harness_correction_sha="f" * 40,
            apply_canonical_provenance_correction=True,
        )

    wrong_trace = {**trace, "graph_version": "text-agent-v2"}
    with pytest.raises(ValueError, match="version"):
        _migration_function()(
            checkpoint,
            corrected_identity=corrected_identity,
            expected_case_queries={"case-1": "query one"},
            runtime_traces=[wrong_trace],
            correction_artifact_path=tmp_path / "provenance-correction.json",
            harness_correction_sha="f" * 40,
            apply_canonical_provenance_correction=True,
        )

    with pytest.raises(ValueError, match="duplicated"):
        _migration_function()(
            checkpoint,
            corrected_identity=corrected_identity,
            expected_case_queries={"case-1": "query one"},
            runtime_traces=[trace, trace],
            correction_artifact_path=tmp_path / "duplicate-traces.json",
            harness_correction_sha="f" * 40,
            apply_canonical_provenance_correction=True,
        )


def test_provenance_migration_rejects_corrupt_duplicate_and_untraced_observations(
    tmp_path: Path,
) -> None:
    checkpoint, _record, corrected_identity, trace = _migration_fixture(tmp_path)
    migration = _migration_function()
    kwargs = {
        "corrected_identity": corrected_identity,
        "expected_case_queries": {"case-1": "query one"},
        "runtime_traces": [trace],
        "correction_artifact_path": tmp_path / "provenance-correction.json",
        "harness_correction_sha": "f" * 40,
        "apply_canonical_provenance_correction": True,
    }

    checkpoint.write_text("{invalid json}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="checkpoint"):
        migration(checkpoint, **kwargs)

    checkpoint, _record, corrected_identity, trace = _migration_fixture(tmp_path / "duplicate")
    checkpoint.write_text(checkpoint.read_text(encoding="utf-8") * 2, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        migration(
            checkpoint,
            **{
                **kwargs,
                "corrected_identity": corrected_identity,
                "runtime_traces": [trace],
                "correction_artifact_path": checkpoint.parent / "provenance-correction.json",
            },
        )

    checkpoint, _record, corrected_identity, trace = _migration_fixture(tmp_path / "missing-trace")
    with pytest.raises(ValueError, match="runtime trace"):
        migration(
            checkpoint,
            **{
                **kwargs,
                "corrected_identity": corrected_identity,
                "runtime_traces": [],
                "correction_artifact_path": checkpoint.parent / "provenance-correction.json",
            },
        )


def test_provenance_migration_requires_explicit_one_time_apply_flag(tmp_path: Path) -> None:
    checkpoint, _record, corrected_identity, trace = _migration_fixture(tmp_path)

    with pytest.raises(ValueError, match="explicit canonical provenance correction"):
        _migration_function()(
            checkpoint,
            corrected_identity=corrected_identity,
            expected_case_queries={"case-1": "query one"},
            runtime_traces=[trace],
            correction_artifact_path=tmp_path / "provenance-correction.json",
            harness_correction_sha="f" * 40,
        )


def test_corrected_checkpoint_resume_keeps_duplicate_corrupt_and_missing_sidecar_guards(
    tmp_path: Path,
) -> None:
    checkpoint, _record, corrected_identity, trace = _migration_fixture(tmp_path)
    _migration_function()(
        checkpoint,
        corrected_identity=corrected_identity,
        expected_case_queries={"case-1": "query one", "case-2": "query two"},
        runtime_traces=[trace],
        correction_artifact_path=tmp_path / "provenance-correction.json",
        harness_correction_sha="f" * 40,
        apply_canonical_provenance_correction=True,
    )
    record_map = load_checkpoint_records(
        checkpoint, corrected_identity, expected_case_ids={"case-1", "case-2"}
    )
    assert set(record_map) == {"case-1"}

    sidecar = checkpoint.with_name(f"{checkpoint.name}.identity.json")
    original_sidecar = sidecar.read_bytes()
    sidecar.unlink()
    with pytest.raises(ValueError, match="no bound run identity"):
        load_checkpoint_records(
            checkpoint, corrected_identity, expected_case_ids={"case-1", "case-2"}
        )
    sidecar.write_bytes(original_sidecar)

    checkpoint.write_text(checkpoint.read_text(encoding="utf-8") * 2, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_checkpoint_records(
            checkpoint, corrected_identity, expected_case_ids={"case-1", "case-2"}
        )
