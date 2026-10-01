from __future__ import annotations

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


def _authorize(**updates: object) -> None:
    values: dict[str, object] = {
        "repo_root": ROOT,
        "run_id": "canonical-M0-P4-test",
        "freeze_commit_sha": _FREEZE,
        "hosted_ci_run_id": 36863378855,
        "hosted_ci_head_sha": _FREEZE,
        "hosted_ci_conclusion": "success",
        "job_conclusions": _jobs(),
    }
    values.update(updates)
    require_p4_inference_authorized(**values)  # type: ignore[arg-type]


def test_p4_authorization_requires_committed_exact_freeze_and_green_hosted_ci(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audited: list[str | None] = []
    monkeypatch.setattr(
        run_identity, "require_committed_behavior", lambda *_args, **_kwargs: _FREEZE
    )
    monkeypatch.setattr(
        preregistration,
        "audit_m5d_b2_preregistration",
        lambda _root, *, allow_current_p4_run_id=None: audited.append(allow_current_p4_run_id),
    )

    _authorize()

    assert audited == ["canonical-M0-P4-test"]


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
    monkeypatch: pytest.MonkeyPatch, field: str, value: object, message: str
) -> None:
    monkeypatch.setattr(
        run_identity, "require_committed_behavior", lambda *_args, **_kwargs: _FREEZE
    )
    monkeypatch.setattr(
        preregistration, "audit_m5d_b2_preregistration", lambda *_args, **_kwargs: {}
    )

    with pytest.raises(ValueError, match=message):
        _authorize(**{field: value})


def test_p4_authorization_rejects_wrong_current_head_and_failed_required_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        run_identity, "require_committed_behavior", lambda *_args, **_kwargs: "c" * 40
    )
    monkeypatch.setattr(
        preregistration, "audit_m5d_b2_preregistration", lambda *_args, **_kwargs: {}
    )

    with pytest.raises(ValueError, match="working-tree HEAD"):
        _authorize()

    monkeypatch.setattr(
        run_identity, "require_committed_behavior", lambda *_args, **_kwargs: _FREEZE
    )
    failed_jobs = _jobs()
    failed_jobs[REQUIRED_HOSTED_CI_JOBS[0]] = "failure"
    with pytest.raises(ValueError, match="required jobs"):
        _authorize(job_conclusions=failed_jobs)


def test_preregistration_contract_requires_complete_identity_field_list() -> None:
    audit = preregistration.audit_m5d_b2_preregistration(ROOT)

    assert audit["canonical_p4_results_present"] is False
    assert audit["release_holdout_accessed"] is False
