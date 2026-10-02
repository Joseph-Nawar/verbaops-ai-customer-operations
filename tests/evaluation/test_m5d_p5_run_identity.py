from __future__ import annotations

import asyncio
import json
import subprocess
from argparse import Namespace
from pathlib import Path

import pytest
import scripts.run_m5d_grounded_eval as grounded_runner
from scripts.run_m5d_grounded_eval import _run

import verbaops.evaluation.m5d_b2_p5_preregistration as p5_preregistration
import verbaops.evaluation.m5d_run_identity as identity_module
from verbaops.agent.evaluation import AgentEvaluationProfile, GroundingCandidate
from verbaops.evaluation.m5d_b2_p5_preregistration import (
    REQUIRED_P5_HOSTED_CI_JOBS,
    audit_m5d_b2_p5_preregistration,
    require_p5_canonical_run_directory,
    require_p5_inference_authorized,
)
from verbaops.evaluation.m5d_run_identity import (
    bind_checkpoint_identity,
    build_agent_evaluation_profile,
    build_p5_run_identity,
    load_checkpoint_records,
    run_identity_sha256,
)

ROOT = Path(__file__).parents[2]


def _head(root: Path = ROOT) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def _profile(grounding: str = "P5_PROMPT_JSON_EXTRACTIVE_SINGLE_PASS") -> AgentEvaluationProfile:
    return build_agent_evaluation_profile(
        grounding,
        evidence_gate="G2_TOP_EVIDENCE_CROSS_ENCODER",
        evidence_gate_threshold=0.2554669,
        model_candidate="M0",
    )


def _jobs() -> dict[str, str]:
    return dict.fromkeys(REQUIRED_P5_HOSTED_CI_JOBS, "success")


def _identity() -> dict[str, object]:
    head = _head()
    return build_p5_run_identity(
        ROOT,
        profile=_profile(),
        run_id="canonical-M0-P5-20261002T120000Z-1234abcd",
        freeze_commit_sha=head,
        hosted_ci_run_id=36999999999,
        hosted_ci_head_sha=head,
        hosted_ci_conclusion="success",
        job_conclusions=_jobs(),
    )


def test_p5_plan_audit_binds_frozen_artifacts_and_p4_closeout() -> None:
    result = audit_m5d_b2_p5_preregistration(ROOT)

    assert result["candidate_id"] == "P5_PROMPT_JSON_EXTRACTIVE_SINGLE_PASS"
    assert result["split"] == "dev"
    assert result["case_count"] == 96
    assert result["plan_sha256"] == (
        "e700ec31f157f47837489fc2d26e1296388405f447701286adc899d7b42fc20e"
    )
    assert result["p4_closeout_classification"] == (
        "P4_EXECUTION_INELIGIBLE_GROQ_RESPONSE_FORMAT_TOOL_CALLING_INCOMPATIBILITY"
    )
    assert result["release_holdout_access_allowed"] is False
    assert result["selection_artifact_allowed"] is False


def test_p5_identity_binds_every_frozen_transport_and_provenance_field() -> None:
    identity = _identity()
    plan = json.loads((ROOT / "evals/rag/v0.2/m5d-b2-p5-experiment-plan.json").read_text())

    assert set(plan["run_identity"]["required_fields"]) <= identity.keys()
    assert identity["p5_experiment_plan_sha256"] == identity["experiment_plan_sha256"]
    assert identity["application_under_test_sha"] == identity["implementation_freeze_sha"]
    assert identity["evaluation_harness_sha"] == identity["implementation_freeze_sha"]
    assert identity["hosted_ci_head_sha"] == identity["implementation_freeze_sha"]
    assert identity["hosted_ci_conclusion"] == "success"
    assert identity["hosted_ci_job_conclusions_sha256"]
    assert identity["grounding_candidate"] == "P5_PROMPT_JSON_EXTRACTIVE_SINGLE_PASS"
    assert identity["agent_prompt_version"] == "text-agent-system-p4-evidence-linked-v1"
    assert identity["agent_graph_version"] == "text-agent-m5d-v1"
    assert identity["grounding_finalizer_version"] == "evidence-linked-extractive-single-pass-v1"
    assert identity["knowledge_terminal_output_transport"] == (
        "prompt_json_plain_content_no_response_format"
    )
    assert identity["tool_choice"] == "auto"
    assert identity["provider_response_format_attached"] is False
    assert identity["retrieval_strategy"] == "hybrid_rrf"
    assert identity["final_evidence_count"] == 5
    assert len(run_identity_sha256(identity)) == 64


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("tool_choice", "required"),
        ("provider_response_format_attached", True),
        ("knowledge_terminal_output_transport", "json_schema"),
        ("p5_experiment_plan_sha256", "0" * 64),
        ("hosted_ci_conclusion", "failure"),
    ],
)
def test_p5_identity_rejects_changes_to_frozen_values(field: str, replacement: object) -> None:
    identity = _identity()

    with pytest.raises(ValueError, match="P5"):
        run_identity_sha256({**identity, field: replacement})


def test_p5_identity_rejects_missing_required_field_and_wrong_candidate() -> None:
    identity = _identity()
    del identity["hosted_ci_job_conclusions_sha256"]
    with pytest.raises(ValueError, match="P5 run identity is missing fields"):
        run_identity_sha256(identity)

    head = _head()
    with pytest.raises(ValueError, match="P5 identity requires"):
        build_p5_run_identity(
            ROOT,
            profile=_profile("P4_EVIDENCE_LINKED_SINGLE_PASS"),
            run_id="canonical-M0-P5-20261002T120000Z-1234abcd",
            freeze_commit_sha=head,
            hosted_ci_run_id=36999999999,
            hosted_ci_head_sha=head,
            hosted_ci_conclusion="success",
            job_conclusions=_jobs(),
        )


def test_p5_identity_digest_rejects_missing_harness_sha_and_invalid_run_id() -> None:
    identity = _identity()
    del identity["evaluation_harness_sha"]
    with pytest.raises(ValueError, match="P5 run identity is missing fields"):
        run_identity_sha256(identity)

    identity = _identity()
    with pytest.raises(ValueError, match="invalid canonical run ID"):
        run_identity_sha256({**identity, "run_id": "canonical-M0-P5-manual"})


def test_p5_authorization_requires_exact_green_ci_and_committed_freeze(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    head = _head()
    monkeypatch.setattr(identity_module, "require_committed_behavior", lambda *_a, **_k: head)

    require_p5_inference_authorized(
        repo_root=ROOT,
        run_id="canonical-M0-P5-20261002T120000Z-1234abcd",
        freeze_commit_sha=head,
        hosted_ci_run_id=36999999999,
        hosted_ci_head_sha=head,
        hosted_ci_conclusion="success",
        job_conclusions=_jobs(),
    )

    failed = _jobs()
    failed[REQUIRED_P5_HOSTED_CI_JOBS[0]] = "failure"
    with pytest.raises(ValueError, match="required jobs"):
        require_p5_inference_authorized(
            repo_root=ROOT,
            run_id="canonical-M0-P5-20261002T120000Z-1234abcd",
            freeze_commit_sha=head,
            hosted_ci_run_id=36999999999,
            hosted_ci_head_sha=head,
            hosted_ci_conclusion="success",
            job_conclusions=failed,
        )


def test_p5_authorization_rejects_multiple_run_namespaces(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(p5_preregistration, "audit_m5d_b2_p5_preregistration", lambda _root: {})
    canonical_root = tmp_path / "evals/rag/v0.2/dev-evidence/canonical"
    (canonical_root / "canonical-M0-P5-20261002T120000Z-1234abcd").mkdir(parents=True)
    (canonical_root / "canonical-M0-P5-20261002T120001Z-abcd1234").mkdir()

    with pytest.raises(ValueError, match="P5 canonical run namespace"):
        require_p5_inference_authorized(
            repo_root=tmp_path,
            run_id="canonical-M0-P5-20261002T120000Z-1234abcd",
            freeze_commit_sha=None,
            hosted_ci_run_id=None,
            hosted_ci_head_sha=None,
            hosted_ci_conclusion=None,
            job_conclusions={},
        )


def test_p5_authorization_rejects_completed_run_before_any_resume(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(p5_preregistration, "audit_m5d_b2_p5_preregistration", lambda _root: {})
    run_id = "canonical-M0-P5-20261002T120000Z-1234abcd"
    run_directory = tmp_path / "evals/rag/v0.2/dev-evidence/canonical" / run_id
    run_directory.mkdir(parents=True)
    (run_directory / "report.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="completed canonical P5 run cannot resume"):
        require_p5_inference_authorized(
            repo_root=tmp_path,
            run_id=run_id,
            freeze_commit_sha=None,
            hosted_ci_run_id=None,
            hosted_ci_head_sha=None,
            hosted_ci_conclusion=None,
            job_conclusions={},
        )


def test_p5_resume_identity_rejects_duplicate_checkpoint_cases(tmp_path: Path) -> None:
    identity = _identity()
    checkpoint = tmp_path / "grounded_cases.jsonl"
    fingerprint = bind_checkpoint_identity(checkpoint, identity)
    record = {
        "case_id": "m5d-v02-shipping-001",
        "run_id": identity["run_id"],
        "run_identity_sha256": fingerprint,
    }
    checkpoint.write_text(json.dumps(record) + "\n" + json.dumps(record) + "\n")

    with pytest.raises(ValueError, match="duplicate checkpoint case ID"):
        load_checkpoint_records(checkpoint, identity, expected_case_ids={"m5d-v02-shipping-001"})


def test_p5_canonical_run_directory_must_be_directly_in_frozen_namespace(
    tmp_path: Path,
) -> None:
    run_id = "canonical-M0-P5-20261002T120000Z-1234abcd"
    expected = tmp_path / "evals/rag/v0.2/dev-evidence/canonical" / run_id

    assert require_p5_canonical_run_directory(tmp_path, expected, run_id=run_id) == expected
    with pytest.raises(ValueError, match="canonical P5 namespace"):
        require_p5_canonical_run_directory(
            tmp_path,
            tmp_path / "evals/rag/v0.2/dev-evidence/canonical/nested" / run_id,
            run_id=run_id,
        )


def test_p5_runner_preflight_reads_only_dev_contract_before_local_service_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded: list[Path] = []
    load_dev = grounded_runner._load_dev_cases_without_holdout

    def observed_dev_loader(path: Path) -> tuple[object, ...]:
        loaded.append(path)
        return load_dev(path)

    def forbidden_all_split_loader(*_args: object, **_kwargs: object) -> object:
        pytest.fail("P5 runner must not load release-holdout rows")

    monkeypatch.setattr(grounded_runner, "_load_dev_cases_without_holdout", observed_dev_loader)
    monkeypatch.setattr(grounded_runner, "load_rag_v02_cases", forbidden_all_split_loader)
    args = Namespace(
        split="dev",
        grounding="P5_PROMPT_JSON_EXTRACTIVE_SINGLE_PASS",
        run_id="canonical-M0-P5-20261002T120000Z-1234abcd",
        database_url=None,
        token=None,
        model_candidate="M0",
        gate="G2_TOP_EVIDENCE_CROSS_ENCODER",
        threshold=0.2554669,
    )

    with pytest.raises(ValueError, match="database and public API bearer token are required"):
        asyncio.run(_run(args))
    assert loaded == [ROOT / "evals/rag/v0.2/questions.jsonl"]


def test_p5_runner_builds_the_p5_identity_after_exact_ci_preflight(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    class IdentityCaptured(Exception):
        pass

    gate_identity = {
        "benchmark_version": "rag-v0.2",
        "split": "dev",
        "dataset_sha256": "a" * 64,
        "knowledge_manifest_sha256": "b" * 64,
        "experiment_plan_sha256": "c" * 64,
        "pre_experiment_sha": identity_module.PRE_EXPERIMENT_SHA,
        "evaluated_git_sha": "d" * 40,
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
    gate_path = tmp_path / "gate.json"
    gate_path.write_text(
        json.dumps(
            {
                "run_id": gate_identity["run_id"],
                "run_identity": gate_identity,
                "run_identity_sha256": run_identity_sha256(gate_identity),
                "evaluated_git_sha": identity_module.CANONICAL_APPLICATION_SHA,
                "pre_experiment_sha": identity_module.PRE_EXPERIMENT_SHA,
                "selected_gate": {
                    "gate": "G2_TOP_EVIDENCE_CROSS_ENCODER",
                    "threshold": 0.2554669,
                },
                "holdout_executed": False,
                "artifacts": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(grounded_runner, "_load_ci_jobs", lambda _path: _jobs())
    monkeypatch.setattr(
        grounded_runner, "_load_dev_cases_without_holdout", lambda _path: (object(),) * 96
    )
    monkeypatch.setattr(
        grounded_runner, "require_canonical_run_directory", lambda *_a, **_k: tmp_path
    )
    monkeypatch.setattr(
        grounded_runner, "require_p5_canonical_run_directory", lambda *_a, **_k: tmp_path
    )
    monkeypatch.setattr(
        grounded_runner,
        "artifact_reference",
        lambda *_a, **_k: {"path": "gate.json", "sha256": "e" * 64},
    )
    monkeypatch.setattr(grounded_runner, "verify_artifact_references", lambda *_a, **_k: None)
    monkeypatch.setattr(grounded_runner, "require_p5_inference_authorized", lambda **_kwargs: None)

    def capture(*_args: object, **kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        raise IdentityCaptured

    monkeypatch.setattr(grounded_runner, "build_p5_run_identity", capture)
    args = Namespace(
        split="dev",
        grounding="P5_PROMPT_JSON_EXTRACTIVE_SINGLE_PASS",
        run_id="canonical-M0-P5-20261002T120000Z-1234abcd",
        run_dir=ROOT
        / "evals/rag/v0.2/dev-evidence/canonical/canonical-M0-P5-20261002T120000Z-1234abcd",
        database_url="unused-until-after-identity",
        token="unused-until-after-identity",
        base_url="http://127.0.0.1:8000",
        timeout_seconds=60,
        inter_case_delay_seconds=0,
        model_candidate="M0",
        gate="G2_TOP_EVIDENCE_CROSS_ENCODER",
        threshold=0.2554669,
        gate_report=gate_path,
        freeze_commit_sha=_head(),
        hosted_ci_run_id=36999999999,
        hosted_ci_head_sha=_head(),
        hosted_ci_conclusion="success",
        hosted_ci_jobs=tmp_path / "jobs.json",
    )
    try:
        asyncio.run(grounded_runner._run(args))
    except IdentityCaptured:
        pass
    else:
        raise AssertionError("P5 runner did not construct the P5 run identity")

    assert (
        captured["profile"].grounding_candidate
        is GroundingCandidate.P5_PROMPT_JSON_EXTRACTIVE_SINGLE_PASS
    )
    assert captured["run_id"] == args.run_id
