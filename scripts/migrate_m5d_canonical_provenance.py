"""Apply the reviewed one-time M5D-B run-identity correction to P0/P1/P2."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from scripts.run_m5d_grounding_sweep_local import _local_environment
from verbaops.conversations.persistence import AgentRun, Message
from verbaops.evaluation.m5d_run_identity import (
    CANONICAL_APPLICATION_SHA,
    artifact_reference,
    build_agent_evaluation_profile,
    load_checkpoint_records,
    migrate_checkpoint_provenance,
    require_canonical_revisions,
    run_identity_sha256,
)
from verbaops.evaluation.rag_v02 import audit_rag_v02, load_rag_v02_cases

ROOT = Path(__file__).resolve().parents[1]
RUNS = {
    "canonical-M0-P0-20260929T124811Z-0d27c8d7": ("P0_CURRENT", 96),
    "canonical-M0-P1-20260930T105712Z-c77394bd": ("P1_PROMPT_V3", 16),
    "canonical-M0-P2-20260930T135336Z-7c951350": (
        "P2_FAIL_CLOSED_CITATIONS",
        32,
    ),
}
GATE = "G2_TOP_EVIDENCE_CROSS_ENCODER"
THRESHOLD = 0.2554669


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object at {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


async def _read_runtime_traces(
    database_url: str, records: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    run_ids = [record.get("agent_run_id") for record in records.values()]
    if any(not isinstance(run_id, str) or not run_id for run_id in run_ids):
        raise ValueError("checkpoint is missing an application-owned agent run ID")
    if len(set(run_ids)) != len(run_ids):
        raise ValueError("checkpoint reuses an agent run ID across observations")
    engine = create_async_engine(database_url, pool_pre_ping=True, echo=False)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            result = await session.execute(
                sa.select(
                    AgentRun.id.label("agent_run_id"),
                    AgentRun.status.label("status"),
                    AgentRun.prompt_version.label("prompt_version"),
                    AgentRun.graph_version.label("graph_version"),
                    Message.content.label("user_message"),
                )
                .select_from(AgentRun)
                .join(Message, Message.id == AgentRun.user_message_id)
                .where(AgentRun.id.in_(run_ids))
            )
            rows = result.mappings().all()
    finally:
        await engine.dispose()

    by_run_id = {str(row["agent_run_id"]): row for row in rows}
    if len(by_run_id) != len(records):
        raise ValueError("persisted runtime trace count does not match checkpoint observations")
    case_by_run_id = {str(record["agent_run_id"]): case_id for case_id, record in records.items()}
    return [
        {
            "case_id": case_by_run_id[run_id],
            "agent_run_id": run_id,
            "status": str(row["status"]),
            "prompt_version": str(row["prompt_version"]),
            "graph_version": str(row["graph_version"]),
            "user_message": str(row["user_message"]),
        }
        for run_id, row in by_run_id.items()
    ]


def _refresh_run_metadata(run_dir: Path, corrected_identity: dict[str, Any], digest: str) -> None:
    checkpoint = run_dir / "grounded_cases.jsonl"
    sidecar = checkpoint.with_name(f"{checkpoint.name}.identity.json")
    correction = run_dir / "provenance-correction.json"
    metadata_path = run_dir / "metadata.json"
    summary_path = run_dir / "run-summary.json"
    report_path = run_dir / "report.json"
    interruption_path = run_dir / "interruption.json"

    report_metrics_before: dict[str, Any] | None = None
    if report_path.is_file():
        report = _read_json(report_path)
        report_metrics_before = {
            key: value
            for key, value in report.items()
            if key not in ("canonical_run_identity_sha256", "evaluation_harness_sha")
        }
        report["canonical_run_identity_sha256"] = digest
        _write_json(report_path, report)
        report_after = _read_json(report_path)
        report_metrics_after = {
            key: value
            for key, value in report_after.items()
            if key not in ("canonical_run_identity_sha256", "evaluation_harness_sha")
        }
        if report_metrics_after != report_metrics_before:
            raise ValueError("P0 report metrics changed during provenance-only migration")

    metadata = _read_json(metadata_path)
    metadata["run_identity"] = corrected_identity
    metadata["run_identity_sha256"] = digest
    metadata["evaluated_git_sha"] = CANONICAL_APPLICATION_SHA
    metadata["evaluation_harness_sha"] = corrected_identity["evaluation_harness_sha"]
    metadata_paths = [checkpoint, sidecar]
    if interruption_path.is_file():
        metadata_paths.append(interruption_path)
    metadata_paths.append(correction)
    metadata["artifacts"] = [artifact_reference(ROOT, path) for path in metadata_paths]
    _write_json(metadata_path, metadata)

    summary = _read_json(summary_path)
    summary["run_identity"] = corrected_identity
    summary["run_identity_sha256"] = digest
    summary["evaluated_git_sha"] = CANONICAL_APPLICATION_SHA
    summary["evaluation_harness_sha"] = corrected_identity["evaluation_harness_sha"]
    summary_paths = [checkpoint, sidecar, metadata_path]
    if report_path.is_file():
        summary_paths.append(report_path)
    if interruption_path.is_file():
        summary_paths.append(interruption_path)
    summary_paths.append(correction)
    summary["artifacts"] = [artifact_reference(ROOT, path) for path in summary_paths]
    _write_json(summary_path, summary)


async def _migrate(run_id: str, *, apply: bool) -> dict[str, Any]:
    candidate, expected_count = RUNS[run_id]
    run_dir = ROOT / "evals/rag/v0.2/dev-evidence/canonical" / run_id
    checkpoint = run_dir / "grounded_cases.jsonl"
    sidecar_path = checkpoint.with_name(f"{checkpoint.name}.identity.json")
    old_sidecar = _read_json(sidecar_path)
    old_identity = old_sidecar.get("identity")
    if not isinstance(old_identity, dict):
        raise ValueError("canonical run identity sidecar is malformed")
    if old_identity.get("run_id") != run_id or old_identity.get("grounding_candidate") != candidate:
        raise ValueError("run ID or candidate differs from the reviewed migration target")
    if old_sidecar.get("run_identity_sha256") != run_identity_sha256(old_identity):
        raise ValueError("old run identity fingerprint is invalid")

    audit = audit_rag_v02(ROOT)
    cases = {
        case.case_id: case.query
        for case in load_rag_v02_cases(ROOT / "evals/rag/v0.2/questions.jsonl")
        if case.split == "dev"
    }
    records = load_checkpoint_records(checkpoint, old_identity, expected_case_ids=set(cases))
    if len(records) != expected_count:
        raise ValueError(f"{run_id} has {len(records)} observations; expected {expected_count}")
    runtime_traces = await _read_runtime_traces(
        _local_environment()[0]["VERBAOPS_DATABASE__URL"], records
    )
    app_sha, harness_sha = require_canonical_revisions(
        ROOT,
        application_sha=CANONICAL_APPLICATION_SHA,
    )
    profile = build_agent_evaluation_profile(
        candidate,
        evidence_gate=GATE,
        evidence_gate_threshold=THRESHOLD,
        model_candidate="M0",
    )
    corrected_identity = {
        **old_identity,
        "benchmark_version": audit.dataset_version,
        "dataset_sha256": audit.dataset_sha256,
        "knowledge_manifest_sha256": audit.knowledge_manifest_sha256,
        "agent_prompt_version": f"text-agent-system-{profile.prompt_version}",
        "agent_graph_version": profile.graph_version,
        "evaluation_harness_sha": harness_sha,
        "evaluated_git_sha": app_sha,
    }
    result = migrate_checkpoint_provenance(
        checkpoint,
        corrected_identity=corrected_identity,
        expected_case_queries=cases,
        runtime_traces=runtime_traces,
        correction_artifact_path=run_dir / "provenance-correction.json",
        harness_correction_sha=harness_sha,
        apply_canonical_provenance_correction=apply,
        dry_run_canonical_provenance_correction=not apply,
    )
    if apply:
        _refresh_run_metadata(
            run_dir,
            corrected_identity,
            result["corrected_identity_sha256"],
        )
    return {
        "run_id": run_id,
        "candidate": candidate,
        "observation_count": expected_count,
        "dry_run": not apply,
        "old_identity_sha256": result["old_identity_sha256"],
        "corrected_identity_sha256": result["corrected_identity_sha256"],
        "application_under_test_sha": app_sha,
        "evaluation_harness_sha": harness_sha,
        "verified_trace_count": result["verified_trace_count"],
        "non_provenance_observation_sha256_before": result[
            "non_provenance_observation_sha256_before"
        ],
        "non_provenance_observation_sha256_after": result[
            "non_provenance_observation_sha256_after"
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", choices=tuple(RUNS), required=True)
    parser.add_argument(
        "--apply-canonical-provenance-correction",
        action="store_true",
        help="explicitly apply the one-time reviewed identity correction",
    )
    args = parser.parse_args()
    result = asyncio.run(_migrate(args.run_id, apply=args.apply_canonical_provenance_correction))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
