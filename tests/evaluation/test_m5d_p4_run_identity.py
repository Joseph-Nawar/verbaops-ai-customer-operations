from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from scripts.run_m5d_grounded_eval import _load_dev_cases_without_holdout

from verbaops.evaluation.m5d_run_identity import (
    build_agent_evaluation_profile,
    build_p4_run_identity,
    run_identity_sha256,
)

ROOT = Path(__file__).parents[2]


def _head_sha(root: Path = ROOT) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def _profile(grounding: str = "P4_EVIDENCE_LINKED_SINGLE_PASS"):
    return build_agent_evaluation_profile(
        grounding,
        evidence_gate="G2_TOP_EVIDENCE_CROSS_ENCODER",
        evidence_gate_threshold=0.2554669,
        model_candidate="M0",
    )


def _identity() -> dict[str, object]:
    head = _head_sha()
    return build_p4_run_identity(
        ROOT,
        profile=_profile(),
        run_id="canonical-M0-P4-identity-test",
        freeze_commit_sha=head,
        hosted_ci_run_id=123456789,
        hosted_ci_head_sha=head,
    )


def test_p4_identity_binds_frozen_contract_and_profile_versions() -> None:
    identity = _identity()

    assert identity["application_under_test_sha"] == identity["freeze_commit_sha"]
    assert identity["evaluated_git_sha"] == identity["application_under_test_sha"]
    assert identity["evaluation_harness_sha"]
    assert identity["hosted_ci_run_id"] == 123456789
    assert identity["hosted_ci_head_sha"] == identity["freeze_commit_sha"]
    assert identity["evidence_gate"] == "G2_TOP_EVIDENCE_CROSS_ENCODER"
    assert identity["evidence_gate_threshold"] == 0.2554669
    assert identity["grounding_candidate"] == "P4_EVIDENCE_LINKED_SINGLE_PASS"
    assert identity["agent_prompt_version"] == "text-agent-system-p4-evidence-linked-v1"
    assert identity["agent_graph_version"] == "text-agent-m5d-v1"
    assert identity["grounding_finalizer_version"] == "evidence-linked-extractive-single-pass-v1"
    assert identity["scorer_definition_commit_sha"] == "fa800f5bfee4ee903905d89bf600642e9ddb0d95"
    assert identity["p4_schema_sha256"] == (
        "c406afdf4100c01328bd86e06d8d4408c25a51a696fb00ff0ea69394ccc625e9"
    )
    plan = json.loads((ROOT / "evals/rag/v0.2/m5d-b2-experiment-plan.json").read_text())
    assert set(plan["run_identity"]["required_fields"]) <= identity.keys()
    assert len(run_identity_sha256(identity)) == 64


def test_p4_identity_derives_prompt_graph_and_finalizer_from_profile() -> None:
    profile = _profile()
    identity = _identity()

    assert identity["agent_prompt_version"] == f"text-agent-system-{profile.prompt_version}"
    assert identity["agent_graph_version"] == profile.graph_version
    assert identity["grounding_finalizer_version"] == profile.grounding_finalizer_version


def test_p4_identity_rejects_other_candidate_and_mismatched_hosted_head() -> None:
    head = _head_sha()
    with pytest.raises(ValueError, match="P4"):
        build_p4_run_identity(
            ROOT,
            profile=_profile("P3_ONE_REPAIR_THEN_FAIL_CLOSED"),
            run_id="canonical-M0-P4-wrong-candidate",
            freeze_commit_sha=head,
            hosted_ci_run_id=123456789,
            hosted_ci_head_sha=head,
        )
    with pytest.raises(ValueError, match="hosted CI head"):
        build_p4_run_identity(
            ROOT,
            profile=_profile(),
            run_id="canonical-M0-P4-wrong-ci-head",
            freeze_commit_sha=head,
            hosted_ci_run_id=123456789,
            hosted_ci_head_sha="a" * 40,
        )
    with pytest.raises(ValueError, match="canonical M0 P4 run ID"):
        build_p4_run_identity(
            ROOT,
            profile=_profile(),
            run_id="not-canonical",
            freeze_commit_sha=head,
            hosted_ci_run_id=123456789,
            hosted_ci_head_sha=head,
        )


@pytest.mark.parametrize(
    "field",
    [
        "scorer_version",
        "scorer_manifest_sha256",
        "scorer_fixture_sha256",
        "scorer_spec_sha256",
        "scorer_implementation_sha256",
        "scorer_definition_commit_sha",
        "p4_schema_sha256",
        "application_under_test_sha",
        "freeze_commit_sha",
        "hosted_ci_run_id",
        "hosted_ci_head_sha",
        "grounding_finalizer_version",
    ],
)
def test_p4_checkpoint_fingerprint_requires_every_frozen_field(field: str) -> None:
    identity = _identity()
    del identity[field]

    with pytest.raises(ValueError, match="P4 run identity is missing fields"):
        run_identity_sha256(identity)


def test_p4_checkpoint_fingerprint_rejects_changed_freeze_or_scorer_bytes() -> None:
    identity = _identity()
    with pytest.raises(ValueError, match="must match"):
        run_identity_sha256({**identity, "freeze_commit_sha": "b" * 40})
    with pytest.raises(ValueError, match="invalid scorer_fixture_sha256"):
        run_identity_sha256({**identity, "scorer_fixture_sha256": "not-a-hash"})


def test_p4_runner_parses_dev_rows_without_parsing_release_holdout(tmp_path: Path) -> None:
    first_dev = (ROOT / "evals/rag/v0.2/questions.jsonl").read_text().splitlines()[0]
    release_row_that_is_not_a_valid_case = '{"split":"release_holdout","private":"unused"}'
    dataset = tmp_path / "questions.jsonl"
    dataset.write_text(first_dev + "\n" + release_row_that_is_not_a_valid_case + "\n")

    cases = _load_dev_cases_without_holdout(dataset)

    assert [case.case_id for case in cases] == ["m5d-v02-shipping-001"]
    assert all(case.split == "dev" for case in cases)
