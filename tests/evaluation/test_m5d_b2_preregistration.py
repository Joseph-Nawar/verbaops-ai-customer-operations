from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import verbaops.evaluation.m5d_b2_preregistration as preregistration
import verbaops.evaluation.m5d_run_identity as run_identity
from verbaops.evaluation.m5d_b2_preregistration import (
    REQUIRED_HOSTED_CI_JOBS,
    require_p4_inference_authorized,
)

ROOT = Path(__file__).parents[2]
_FREEZE = "a" * 40


def _jobs() -> dict[str, str]:
    return dict.fromkeys(REQUIRED_HOSTED_CI_JOBS, "success")


def _authorize(repo_root: Path = ROOT, **updates: object) -> None:
    values: dict[str, object] = {
        "repo_root": repo_root,
        "run_id": "canonical-M0-P4-test",
        "freeze_commit_sha": _FREEZE,
        "hosted_ci_run_id": 36863378855,
        "hosted_ci_head_sha": _FREEZE,
        "hosted_ci_conclusion": "success",
        "job_conclusions": _jobs(),
    }
    values.update(updates)
    require_p4_inference_authorized(**values)  # type: ignore[arg-type]


def _copy_frozen_contract(destination: Path) -> Path:
    manifest = json.loads(
        (ROOT / "evals/rag/v0.2/scorer-v2/manifest.json").read_text(encoding="utf-8")
    )
    paths = {
        "evals/rag/v0.2/questions.jsonl",
        "evals/rag/v0.2/m5d-b2-experiment-plan.json",
        "evals/rag/v0.2/scorer-v2/manifest.json",
        "evals/rag/v0.2/scorer-v2/fixtures.json",
        "evals/rag/v0.2/scorer-v2/spec.json",
        "evals/rag/v0.2/scorer-v2/p4-output.schema.json",
        manifest["scorer_implementation_path"],
        "knowledge/novacommerce/manifest.json",
        *manifest["source_corpus_sha256"],
    }
    for relative in paths:
        source = ROOT / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return destination


def test_p4_authorization_requires_committed_exact_freeze_and_green_hosted_ci(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    copied_root = _copy_frozen_contract(tmp_path / "repo")
    audited: list[Path] = []
    monkeypatch.setattr(
        run_identity, "require_committed_behavior", lambda *_args, **_kwargs: _FREEZE
    )
    monkeypatch.setattr(
        preregistration,
        "audit_m5d_b2_preregistration",
        lambda root: audited.append(root),
    )

    _authorize(copied_root)

    assert audited == [copied_root]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("freeze_commit_sha", None, "freeze commit SHA"),
        ("hosted_ci_run_id", None, "hosted CI run ID"),
        ("hosted_ci_head_sha", "b" * 40, "exact freeze commit"),
        ("hosted_ci_conclusion", "failure", "successful hosted CI"),
    ],
)
def test_p4_authorization_rejects_missing_or_mismatched_ci_provenance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    copied_root = _copy_frozen_contract(tmp_path / "repo")
    monkeypatch.setattr(
        run_identity, "require_committed_behavior", lambda *_args, **_kwargs: _FREEZE
    )
    monkeypatch.setattr(
        preregistration, "audit_m5d_b2_preregistration", lambda *_args, **_kwargs: {}
    )

    with pytest.raises(ValueError, match=message):
        _authorize(copied_root, **{field: value})


def test_p4_authorization_rejects_wrong_current_head_and_failed_required_job(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    copied_root = _copy_frozen_contract(tmp_path / "repo")
    monkeypatch.setattr(
        run_identity, "require_committed_behavior", lambda *_args, **_kwargs: "c" * 40
    )
    monkeypatch.setattr(
        preregistration, "audit_m5d_b2_preregistration", lambda *_args, **_kwargs: {}
    )

    with pytest.raises(ValueError, match="working-tree HEAD"):
        _authorize(copied_root)

    monkeypatch.setattr(
        run_identity, "require_committed_behavior", lambda *_args, **_kwargs: _FREEZE
    )
    failed_jobs = _jobs()
    failed_jobs[REQUIRED_HOSTED_CI_JOBS[0]] = "failure"
    with pytest.raises(ValueError, match="required jobs"):
        _authorize(copied_root, job_conclusions=failed_jobs)


def test_preregistration_contract_requires_complete_identity_field_list() -> None:
    audit = preregistration.audit_m5d_b2_preregistration(ROOT)

    assert audit["canonical_p4_results_present"] is True
    assert audit["release_holdout_accessed"] is False
    assert audit["selection_json_present"] is False


def test_final_p4_closeout_audit_validates_canonical_evidence() -> None:
    audit = preregistration.audit_m5d_b2_p4_closeout(ROOT)

    assert audit["run_id"] == "canonical-M0-P4-20261001T173102Z-31113cc8"
    assert audit["classification"] == (
        "P4_EXECUTION_INELIGIBLE_GROQ_RESPONSE_FORMAT_TOOL_CALLING_INCOMPATIBILITY"
    )
    assert audit["completed_cases"] == 1
    assert audit["expected_cases"] == 96
    assert audit["completed_case_ids"] == ["m5d-v02-shipping-001"]
    assert audit["blocked_case_id"] == "m5d-v02-shipping-002"
    assert audit["observation_count"] == 1
    assert audit["trace_sidecar_count"] == 1
    assert audit["report_generated"] is False
    assert audit["quality_metrics_computed"] is False
    assert audit["stage4_dev_eligible"] is False
    assert audit["m5d_c_eligible"] is False
    assert audit["release_holdout_executed"] is False
    assert audit["selection_json_present"] is False
    assert audit["canonical_evidence_status"] == "COMPLETE"
    assert audit["artifact_hashes_valid"] is True


def test_closed_p4_run_cannot_resume_or_start_a_second_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        run_identity, "require_committed_behavior", lambda *_args, **_kwargs: _FREEZE
    )
    for run_id in (
        "canonical-M0-P4-20261001T173102Z-31113cc8",
        "canonical-M0-P4-new-attempt",
    ):
        values: dict[str, object] = {
            "repo_root": ROOT,
            "run_id": run_id,
            "freeze_commit_sha": _FREEZE,
            "hosted_ci_run_id": 36863378855,
            "hosted_ci_head_sha": _FREEZE,
            "hosted_ci_conclusion": "success",
            "job_conclusions": _jobs(),
        }
        with pytest.raises(ValueError, match="closed"):
            require_p4_inference_authorized(**values)  # type: ignore[arg-type]


def test_multiple_or_unrelated_p4_namespaces_remain_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repo"
    canonical_root = repo_root / "evals/rag/v0.2/dev-evidence/canonical"
    canonical_root.mkdir(parents=True)
    (canonical_root / "canonical-M0-P4-unrelated").mkdir()
    (canonical_root / "canonical-M0-P4-second").mkdir()
    monkeypatch.setattr(
        preregistration,
        "audit_m5d_b2_preregistration",
        lambda _root, **_kwargs: {},
    )
    monkeypatch.setattr(
        run_identity, "require_committed_behavior", lambda *_args, **_kwargs: _FREEZE
    )

    values: dict[str, object] = {
        "repo_root": repo_root,
        "run_id": "canonical-M0-P4-requested",
        "freeze_commit_sha": _FREEZE,
        "hosted_ci_run_id": 1,
        "hosted_ci_head_sha": _FREEZE,
        "hosted_ci_conclusion": "success",
        "job_conclusions": _jobs(),
    }
    with pytest.raises(ValueError, match="canonical P4 run namespace"):
        require_p4_inference_authorized(**values)  # type: ignore[arg-type]
