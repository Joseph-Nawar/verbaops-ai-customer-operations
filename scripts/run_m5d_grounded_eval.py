"""Resume one rag-v0.2 DEV grounding candidate over the public agent API."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from verbaops.evaluation.m5d_run_identity import (
    CANONICAL_APPLICATION_SHA,
    PRE_EXPERIMENT_SHA,
    artifact_reference,
    bind_checkpoint_identity,
    build_agent_evaluation_profile,
    load_checkpoint_records,
    require_canonical_revisions,
    require_canonical_run_directory,
    run_identity_sha256,
    verify_artifact_references,
)
from verbaops.evaluation.rag_grounding import (
    M5dCaseExecutionError,
    run_grounded_evaluation,
    score_grounded_records,
    score_p4_grounded_records,
)
from verbaops.evaluation.rag_v02 import (
    audit_rag_v02,
    guard_rag_v02_split,
    load_rag_v02_cases,
    sha256_file,
)
from verbaops.evaluation.rag_v02_gates import EvidenceGate
from verbaops.evaluation.rag_v02_grounded_runtime import PublicRagV02AgentAdapter
from verbaops.retrieval.profile import PRODUCTION_RETRIEVAL_PROFILE

ROOT = Path(__file__).resolve().parents[1]
GROUNDING_CANDIDATES = {
    "P0_CURRENT",
    "P1_PROMPT_V3",
    "P2_FAIL_CLOSED_CITATIONS",
    "P3_ONE_REPAIR_THEN_FAIL_CLOSED",
}


async def _run(args: argparse.Namespace) -> None:
    guard_rag_v02_split(args.split)
    if args.split != "dev":
        raise ValueError("M5D grounded runner executes only --split dev")
    audit = audit_rag_v02(ROOT)
    cases = tuple(
        case
        for case in load_rag_v02_cases(ROOT / "evals/rag/v0.2/questions.jsonl")
        if case.split == "dev"
    )
    if len(cases) != 96:
        raise ValueError("rag-v0.2 DEV must contain exactly 96 cases")
    if not args.database_url or not args.token:
        raise ValueError("database and public API bearer token are required")
    if args.grounding not in GROUNDING_CANDIDATES:
        raise ValueError("grounding candidate is not preregistered")
    if args.model_candidate != "M0":
        raise ValueError("only M0 is executable in this local M5D run")
    gate = EvidenceGate(args.gate)
    gate_report = json.loads(args.gate_report.read_text(encoding="utf-8"))
    selected_gate = gate_report.get("selected_gate")
    if not isinstance(selected_gate, dict):
        raise ValueError("gate report has no eligible selected gate")
    if selected_gate.get("gate") != gate.value:
        raise ValueError("grounding candidate gate differs from the selected DEV gate")
    selected_threshold = selected_gate.get("threshold")
    if (
        isinstance(selected_threshold, bool)
        or not isinstance(selected_threshold, int | float)
        or selected_threshold != args.threshold
    ):
        raise ValueError("grounding threshold differs from the selected DEV threshold")
    if gate_report.get("holdout_executed") is not False:
        raise ValueError("gate report does not attest DEV-only execution")

    evaluated_git_sha, evaluation_harness_sha = require_canonical_revisions(
        ROOT,
        application_sha=CANONICAL_APPLICATION_SHA,
    )
    gate_identity = gate_report.get("run_identity")
    if (
        not isinstance(gate_identity, dict)
        or gate_report.get("evaluated_git_sha") != evaluated_git_sha
        or gate_report.get("pre_experiment_sha") != PRE_EXPERIMENT_SHA
        or gate_identity.get("run_id") != gate_report.get("run_id")
    ):
        raise ValueError("gate report is not bound to the committed canonical implementation")
    if gate_report.get("run_identity_sha256") != run_identity_sha256(gate_identity):
        raise ValueError("gate report run identity checksum is invalid")
    gate_artifacts = gate_report.get("artifacts")
    if not isinstance(gate_artifacts, list):
        raise ValueError("gate report is missing hash-bound artifacts")
    verify_artifact_references(ROOT, gate_artifacts)
    require_canonical_run_directory(ROOT, args.run_dir, run_id=args.run_id)
    profile = build_agent_evaluation_profile(
        args.grounding,
        evidence_gate=gate.value,
        evidence_gate_threshold=args.threshold,
        model_candidate=args.model_candidate,
    )
    run_identity = {
        "benchmark_version": audit.dataset_version,
        "split": "dev",
        "dataset_sha256": audit.dataset_sha256,
        "knowledge_manifest_sha256": audit.knowledge_manifest_sha256,
        "experiment_plan_sha256": sha256_file(ROOT / "evals/rag/v0.2/experiment-plan.json"),
        "pre_experiment_sha": PRE_EXPERIMENT_SHA,
        "evaluated_git_sha": evaluated_git_sha,
        "evaluation_harness_sha": evaluation_harness_sha,
        "evidence_gate": gate.value,
        "evidence_gate_threshold": args.threshold,
        "grounding_candidate": args.grounding,
        "model_candidate": args.model_candidate,
        "retrieval_profile_version": PRODUCTION_RETRIEVAL_PROFILE.version,
        "agent_prompt_version": f"text-agent-system-{profile.prompt_version}",
        "agent_graph_version": profile.graph_version,
        "model_revision": "groq/openai/gpt-oss-120b"
        if args.model_candidate == "M0"
        else "M1-local",
        "run_id": args.run_id,
    }
    args.run_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = args.run_dir / "grounded_cases.jsonl"
    identity_digest = bind_checkpoint_identity(checkpoint, run_identity)
    engine = create_async_engine(args.database_url, pool_pre_ping=True, echo=False)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    secrets_to_hide = tuple(
        value
        for value in (
            os.environ.get("VERBAOPS_AGENT_FAST_API_KEY", ""),
            os.environ.get("VERBAOPS_AUTH__DEVELOPMENT_TOKEN", ""),
            os.environ.get("NOVACOMMERCE_SERVICE_TOKEN", ""),
            os.environ.get("LITELLM_MASTER_KEY", ""),
        )
        if value
    )
    provenance = {
        "evaluated_git_sha": evaluated_git_sha,
        "evaluation_harness_sha": evaluation_harness_sha,
        "evaluation_worktree_dirty": False,
        "run_identity_sha256": identity_digest,
        "run_id": args.run_id,
    }
    blocked_error: M5dCaseExecutionError | None = None
    try:
        async with httpx.AsyncClient(timeout=args.timeout_seconds) as client:
            adapter = PublicRagV02AgentAdapter(
                args.base_url,
                args.token,
                client,
                sessions,
                grounding_candidate=args.grounding,
                gate_threshold=args.threshold,
                p4_trace_run_directory=(
                    args.run_dir if args.grounding == "P4_EVIDENCE_LINKED_SINGLE_PASS" else None
                ),
                p4_trace_run_id=(
                    args.run_id if args.grounding == "P4_EVIDENCE_LINKED_SINGLE_PASS" else None
                ),
            )
            new_records = await run_grounded_evaluation(
                cases,
                adapter,
                checkpoint,
                secrets_to_hide=secrets_to_hide,
                delay_seconds_between_cases=args.inter_case_delay_seconds,
                record_metadata=provenance,
                run_identity=run_identity,
            )
    except M5dCaseExecutionError as error:
        blocked_error = error
    finally:
        await engine.dispose()
    if blocked_error is not None:
        _write_interrupted_summary(
            args,
            cases=cases,
            run_identity=run_identity,
            identity_digest=identity_digest,
            evaluated_git_sha=evaluated_git_sha,
            error=blocked_error,
        )
        raise blocked_error
    record_map = load_checkpoint_records(
        checkpoint, run_identity, expected_case_ids={case.case_id for case in cases}
    )
    records = [record_map[case.case_id] for case in cases if case.case_id in record_map]
    report = (
        score_p4_grounded_records(cases, records, args.threshold, repo_root=ROOT)
        if args.grounding == "P4_EVIDENCE_LINKED_SINGLE_PASS"
        else score_grounded_records(cases, records, args.threshold)
    )
    costs = [float(record["cost_usd"]) for record in records if record.get("cost_usd") is not None]
    report["total_cost_usd_over_costed_observations"] = sum(costs) if costs else None
    report["mean_cost_usd_over_costed_observations"] = sum(costs) / len(costs) if costs else None
    report["cost_metadata_observations"] = len(costs)
    report["model_metadata"] = _metadata_summary(records)
    metadata = {
        "run_id": args.run_id,
        "canonical": True,
        "run_identity": run_identity,
        "run_identity_sha256": identity_digest,
        "dataset_version": audit.dataset_version,
        "split": "dev",
        "case_count": len(cases),
        "dataset_sha256": audit.dataset_sha256,
        "knowledge_manifest_sha256": audit.knowledge_manifest_sha256,
        "experiment_plan_sha256": sha256_file(ROOT / "evals/rag/v0.2/experiment-plan.json"),
        "selected_gate": gate.value,
        "threshold": args.threshold,
        "grounding_candidate": args.grounding,
        "model_candidate": args.model_candidate,
        "completed_case_count": len(records),
        "cases_without_evaluation_provenance": sum(
            "evaluated_git_sha" not in record for record in records
        ),
        "cases_collected_before_throttle": sum(
            "evaluation_inter_case_delay_seconds" not in record for record in records
        ),
        "inter_case_delay_seconds_for_new_cases": args.inter_case_delay_seconds,
        "new_case_count": len(new_records),
        **provenance,
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "holdout_executed": False,
        "production_promoted": False,
        "credentials_persisted": False,
    }
    identity_path = checkpoint.with_name(f"{checkpoint.name}.identity.json")
    metadata_path = args.run_dir / "metadata.json"
    report_path = args.run_dir / "report.json"
    metadata["artifacts"] = [
        artifact_reference(ROOT, checkpoint),
        artifact_reference(ROOT, identity_path),
    ]
    correction_path = args.run_dir / "provenance-correction.json"
    if correction_path.is_file():
        metadata["artifacts"].append(artifact_reference(ROOT, correction_path))
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report["canonical_run_id"] = args.run_id
    report["canonical_run_identity_sha256"] = identity_digest
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {
        "canonical": True,
        "run_id": args.run_id,
        "run_identity": run_identity,
        "run_identity_sha256": run_identity_sha256(run_identity),
        "evaluated_git_sha": evaluated_git_sha,
        "evaluation_harness_sha": evaluation_harness_sha,
        "pre_experiment_sha": PRE_EXPERIMENT_SHA,
        "completed_cases": len(records),
        "artifacts": [
            artifact_reference(ROOT, checkpoint),
            artifact_reference(ROOT, identity_path),
            artifact_reference(ROOT, metadata_path),
            artifact_reference(ROOT, report_path),
        ],
    }
    if correction_path.is_file():
        summary["artifacts"].append(artifact_reference(ROOT, correction_path))
    (args.run_dir / "run-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "run_id": args.run_id,
                "completed_cases": len(records),
                "grounding_candidate": args.grounding,
                "model_candidate": args.model_candidate,
                "citation_precision": report["citation_precision"],
                "groundedness": report["groundedness"],
                "expected_fact_coverage": report["expected_fact_coverage"],
                "holdout_executed": False,
            },
            sort_keys=True,
        )
    )


def _metadata_summary(records: list[dict[str, Any]]) -> dict[str, object]:
    models = sorted({str(record["model"]) for record in records if record.get("model")})
    providers = sorted({str(record["provider"]) for record in records if record.get("provider")})
    aliases = sorted(
        {str(record["capability_alias"]) for record in records if record.get("capability_alias")}
    )
    return {
        "models": models,
        "providers": providers,
        "capability_aliases": aliases,
        "observations_with_model_metadata": sum(bool(record.get("model")) for record in records),
    }


def _write_interrupted_summary(
    args: argparse.Namespace,
    *,
    cases: tuple[Any, ...],
    run_identity: dict[str, Any],
    identity_digest: str,
    evaluated_git_sha: str,
    error: M5dCaseExecutionError,
) -> None:
    checkpoint = args.run_dir / "grounded_cases.jsonl"
    identity_path = checkpoint.with_name(f"{checkpoint.name}.identity.json")
    completed = load_checkpoint_records(
        checkpoint, run_identity, expected_case_ids={case.case_id for case in cases}
    )
    interruption_path = args.run_dir / "interruption.json"
    interruption = {
        "run_id": args.run_id,
        "run_identity_sha256": identity_digest,
        "grounding_candidate": args.grounding,
        "model_candidate": args.model_candidate,
        "blocked_case_id": error.case_id,
        "error_type": error.error_type,
        "http_status_code": error.status_code,
        "completed_case_count": len(completed),
        "holdout_executed": False,
    }
    interruption_path.write_text(
        json.dumps(interruption, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    metadata_path = args.run_dir / "metadata.json"
    metadata = {
        "run_id": args.run_id,
        "canonical": True,
        "run_status": "INTERRUPTED",
        "run_identity": run_identity,
        "run_identity_sha256": identity_digest,
        "evaluated_git_sha": evaluated_git_sha,
        "evaluation_harness_sha": run_identity["evaluation_harness_sha"],
        "pre_experiment_sha": PRE_EXPERIMENT_SHA,
        "completed_case_count": len(completed),
        "blocked_case_id": error.case_id,
        "artifacts": [
            artifact_reference(ROOT, checkpoint),
            artifact_reference(ROOT, identity_path),
            artifact_reference(ROOT, interruption_path),
        ],
    }
    correction_path = args.run_dir / "provenance-correction.json"
    if correction_path.is_file():
        metadata["artifacts"].append(artifact_reference(ROOT, correction_path))
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    summary = {
        "canonical": True,
        "run_status": "INTERRUPTED",
        "run_id": args.run_id,
        "run_identity": run_identity,
        "run_identity_sha256": identity_digest,
        "evaluated_git_sha": evaluated_git_sha,
        "evaluation_harness_sha": run_identity["evaluation_harness_sha"],
        "pre_experiment_sha": PRE_EXPERIMENT_SHA,
        "completed_cases": len(completed),
        "blocked_case_id": error.case_id,
        "artifacts": [
            artifact_reference(ROOT, checkpoint),
            artifact_reference(ROOT, identity_path),
            artifact_reference(ROOT, interruption_path),
            artifact_reference(ROOT, metadata_path),
        ],
    }
    if correction_path.is_file():
        summary["artifacts"].append(artifact_reference(ROOT, correction_path))
    (args.run_dir / "run-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="dev", choices=("dev", "release_holdout"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--database-url", default=os.environ.get("VERBAOPS_DATABASE__URL"))
    parser.add_argument(
        "--base-url", default=os.environ.get("VERBAOPS_AGENT_API_URL", "http://localhost:8000")
    )
    parser.add_argument("--token", default=os.environ.get("VERBAOPS_AUTH__DEVELOPMENT_TOKEN"))
    parser.add_argument("--gate-report", type=Path, required=True)
    parser.add_argument("--gate", choices=tuple(gate.value for gate in EvidenceGate), required=True)
    parser.add_argument("--threshold", type=float, required=True)
    parser.add_argument("--grounding", choices=sorted(GROUNDING_CANDIDATES), required=True)
    parser.add_argument("--model-candidate", choices=("M0", "M1"), default="M0")
    parser.add_argument("--inter-case-delay-seconds", type=float, default=0.0)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    args = parser.parse_args()
    try:
        asyncio.run(_run(args))
    except (OSError, ValueError, KeyError, httpx.HTTPError, M5dCaseExecutionError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
