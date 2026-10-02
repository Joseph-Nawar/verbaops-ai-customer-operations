from __future__ import annotations

import asyncio
import json
import re
import subprocess
from argparse import Namespace
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from scripts import run_m5d_stage4_dev_eval as stage4_runner
from scripts.run_m5d_stage4_dev_eval import _p5_rag_report_meets_stage4_gate, _run

from verbaops.agent.p4_grounding import empty_p4_response_diagnostics
from verbaops.evaluation.m5d_b2_p5_preregistration import REQUIRED_P5_HOSTED_CI_JOBS
from verbaops.evaluation.m5d_run_identity import (
    artifact_reference,
    bind_checkpoint_identity,
    build_agent_evaluation_profile,
    build_p5_run_identity,
    run_identity_sha256,
)
from verbaops.evaluation.p5_trace import P5TraceStore, project_p5_diagnostics


def _args(
    *,
    split: str = "dev",
    grounding: str = "P4_EVIDENCE_LINKED_SINGLE_PASS",
    gate: str = "G2_TOP_EVIDENCE_CROSS_ENCODER",
    threshold: float = 0.2554669,
    p5_rag_run_dir: Path | None = None,
) -> Namespace:
    return Namespace(
        split=split,
        grounding=grounding,
        model_candidate="M0",
        gate=gate,
        threshold=threshold,
        database_url=None,
        token=None,
        p5_rag_run_dir=p5_rag_run_dir,
    )


def test_stage4_dev_runner_accepts_p4_without_starting_inference() -> None:
    with pytest.raises(ValueError, match="database and public API bearer token"):
        asyncio.run(_run(_args()))


def test_stage4_p5_candidate_requires_complete_eligible_rag_evidence_before_services() -> None:
    with pytest.raises(ValueError, match="P5 requires complete eligible canonical RAG evidence"):
        asyncio.run(
            _run(
                _args(
                    grounding="P5_PROMPT_JSON_EXTRACTIVE_SINGLE_PASS",
                    p5_rag_run_dir=None,
                )
            )
        )


def _qualifying_p5_report() -> dict[str, object]:
    return {
        "scorer_version": "rag-v0.2-scorer-v2",
        "citation_precision": {"numerator": 96, "denominator": 96, "value": 1.0},
        "groundedness": {"numerator": 9, "denominator": 10, "value": 0.9},
        "unsupported_claim_rate": 0.1,
        "expected_fact_coverage": {"numerator": 54, "denominator": 72, "value": 0.75},
        "p5_diagnostics": {
            "zero_fabricated_or_non_supplied_evidence_handles": True,
            "fabricated_or_non_supplied_evidence_handle_count": 0,
        },
    }


def test_stage4_p5_gate_requires_every_rag_floor_and_trust_invariant() -> None:
    assert _p5_rag_report_meets_stage4_gate(_qualifying_p5_report()) is True

    failures = (
        {"citation_precision": {"numerator": 94, "denominator": 100, "value": 0.94}},
        {"citation_precision": {"numerator": 0, "denominator": 0, "value": None}},
        {"groundedness": {"numerator": 8, "denominator": 10, "value": 0.8}},
        {"groundedness": {"numerator": 0, "denominator": 0, "value": None}},
        {"unsupported_claim_rate": 0.11},
        {"expected_fact_coverage": {"numerator": 50, "denominator": 72, "value": 0.69}},
        {"p5_diagnostics": {"zero_fabricated_or_non_supplied_evidence_handles": False}},
        {
            "p5_diagnostics": {
                "zero_fabricated_or_non_supplied_evidence_handles": True,
                "fabricated_or_non_supplied_evidence_handle_count": 1,
            }
        },
    )
    for update in failures:
        report = _qualifying_p5_report()
        report.update(update)
        assert _p5_rag_report_meets_stage4_gate(report) is False


def test_stage4_accepts_only_complete_identity_and_trace_bound_p5_rag_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_dataset = Path(__file__).parents[2] / "evals/rag/v0.2/questions.jsonl"
    dev_rows: list[str] = []
    case_ids: list[str] = []
    from verbaops.evaluation.rag_v02 import RagV02Case

    with source_dataset.open(encoding="utf-8") as source:
        for line in source:
            if not re.search(r'"split"\s*:\s*"dev"', line):
                continue
            case = RagV02Case.model_validate_json(line)
            dev_rows.append(line.rstrip("\n"))
            case_ids.append(case.case_id)
            if len(case_ids) == 96:
                break
    assert len(case_ids) == 96
    dataset = tmp_path / "evals/rag/v0.2/questions.jsonl"
    dataset.parent.mkdir(parents=True)
    dataset.write_text("\n".join(dev_rows) + "\n", encoding="utf-8")

    run_id = "canonical-M0-P5-20261002T120000Z-1234abcd"
    run_directory = tmp_path / "evals/rag/v0.2/dev-evidence/canonical" / run_id
    run_directory.mkdir(parents=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(__file__).parents[2],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    jobs = dict.fromkeys(REQUIRED_P5_HOSTED_CI_JOBS, "success")
    identity = build_p5_run_identity(
        Path(__file__).parents[2],
        profile=build_agent_evaluation_profile(
            "P5_PROMPT_JSON_EXTRACTIVE_SINGLE_PASS",
            evidence_gate="G2_TOP_EVIDENCE_CROSS_ENCODER",
            evidence_gate_threshold=0.2554669,
            model_candidate="M0",
        ),
        run_id=run_id,
        freeze_commit_sha=head,
        hosted_ci_run_id=36999999999,
        hosted_ci_head_sha=head,
        hosted_ci_conclusion="success",
        job_conclusions=jobs,
    )
    fingerprint = run_identity_sha256(identity)
    checkpoint = run_directory / "grounded_cases.jsonl"
    bind_checkpoint_identity(checkpoint, identity)
    identity_path = checkpoint.with_name(f"{checkpoint.name}.identity.json")
    trace_store = P5TraceStore(run_directory, run_id)
    diagnostics = project_p5_diagnostics(
        empty_p4_response_diagnostics(), knowledge_mode_active=False, tool_path_entered=False
    )
    checkpoint_records: list[dict[str, object]] = []
    trace_refs: list[dict[str, str]] = []
    for case_id in case_ids:
        agent_run_id = uuid4()
        artifact = trace_store.write(agent_run_id, diagnostics)
        trace_reference = {
            "path": artifact.path.relative_to(tmp_path).as_posix(),
            "sha256": artifact.sha256,
        }
        trace_refs.append(trace_reference)
        checkpoint_records.append(
            {
                "case_id": case_id,
                "run_id": run_id,
                "run_identity_sha256": fingerprint,
                "agent_run_id": str(agent_run_id),
                "p5_diagnostics": diagnostics,
                "p5_trace_artifact": {
                    "path": artifact.relative_path,
                    "sha256": artifact.sha256,
                },
            }
        )
    checkpoint.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in checkpoint_records),
        encoding="utf-8",
    )

    gate_path = tmp_path / "gate.json"
    gate_path.write_text("{}", encoding="utf-8")
    metadata = {
        "grounding_candidate": "P5_PROMPT_JSON_EXTRACTIVE_SINGLE_PASS",
        "split": "dev",
        "completed_case_count": 96,
        "execution_eligibility": "EXECUTION_ELIGIBLE",
        "holdout_executed": False,
        "run_identity": identity,
        "run_identity_sha256": fingerprint,
        "artifacts": [
            artifact_reference(tmp_path, checkpoint),
            artifact_reference(tmp_path, identity_path),
            *trace_refs,
        ],
    }
    metadata_path = run_directory / "metadata.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    report = {
        **_qualifying_p5_report(),
        "canonical_run_id": run_id,
        "canonical_run_identity_sha256": fingerprint,
    }
    report_path = run_directory / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    summary = {
        "canonical": True,
        "run_id": run_id,
        "completed_cases": 96,
        "holdout_executed": False,
        "run_identity": identity,
        "run_identity_sha256": fingerprint,
        "artifacts": [
            artifact_reference(tmp_path, checkpoint),
            artifact_reference(tmp_path, identity_path),
            artifact_reference(tmp_path, metadata_path),
            artifact_reference(tmp_path, report_path),
            *trace_refs,
        ],
        "input_gate_artifacts": [artifact_reference(tmp_path, gate_path)],
    }
    (run_directory / "run-summary.json").write_text(json.dumps(summary), encoding="utf-8")

    monkeypatch.setattr(stage4_runner, "ROOT", tmp_path)
    monkeypatch.setattr(stage4_runner, "audit_m5d_b2_p5_preregistration", lambda _root: {})
    stage4_runner._require_complete_eligible_p5_rag_run(run_directory)

    invalid_report = {**report, "groundedness": {"numerator": 8, "denominator": 10, "value": 0.8}}
    report_path.write_text(json.dumps(invalid_report), encoding="utf-8")
    summary_artifacts = cast(list[dict[str, str]], summary["artifacts"])
    summary["artifacts"] = [
        artifact_reference(tmp_path, report_path)
        if reference["path"] == report_path.relative_to(tmp_path).as_posix()
        else reference
        for reference in summary_artifacts
    ]
    (run_directory / "run-summary.json").write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(ValueError, match="does not pass every frozen quality floor"):
        stage4_runner._require_complete_eligible_p5_rag_run(run_directory)


def test_stage4_dev_runner_rejects_p4_release_holdout_before_loading_cases() -> None:
    with pytest.raises(ValueError, match="only --split dev"):
        asyncio.run(_run(_args(split="release_holdout")))


def test_stage4_dev_runner_rejects_unknown_candidate() -> None:
    with pytest.raises(ValueError, match="grounding candidate is not preregistered"):
        asyncio.run(_run(_args(grounding="P9_UNKNOWN")))


@pytest.mark.parametrize(
    ("gate", "threshold"),
    [("G1_DENSE_SIMILARITY", 0.2554669), ("G2_TOP_EVIDENCE_CROSS_ENCODER", 0.4)],
)
def test_stage4_dev_runner_rejects_p4_profile_outside_frozen_g2(
    gate: str, threshold: float
) -> None:
    with pytest.raises(ValueError, match="P4 requires the frozen G2 gate and threshold"):
        asyncio.run(_run(_args(gate=gate, threshold=threshold)))
