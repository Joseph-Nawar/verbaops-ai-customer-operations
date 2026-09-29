"""Run checkpoint-safe rag-v0.2 DEV evidence-gate calibration only."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import httpx
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from verbaops.config.settings import LLMSettings
from verbaops.evaluation.m5d_run_identity import (
    PRE_EXPERIMENT_SHA,
    artifact_reference,
    bind_checkpoint_identity,
    load_checkpoint_records,
    require_canonical_run_directory,
    require_committed_behavior,
    run_identity_sha256,
)
from verbaops.evaluation.rag_v02 import (
    audit_rag_v02,
    guard_rag_v02_split,
    load_rag_v02_cases,
    sha256_file,
)
from verbaops.evaluation.rag_v02_gate_runtime import PostgresM5dGateAdapter
from verbaops.evaluation.rag_v02_gates import (
    GateObservation,
    calibrate_evidence_gate,
    select_evidence_gate,
)
from verbaops.knowledge.embeddings import EmbeddingClient
from verbaops.knowledge.profiles import EMBEDDING_MODEL
from verbaops.retrieval.evidence_gate import EvidenceGate
from verbaops.retrieval.profile import PRODUCTION_RETRIEVAL_PROFILE, RERANKER_MODEL
from verbaops.retrieval.reranker import RerankerClient

ROOT = Path(__file__).resolve().parents[1]
TENANT_ID = UUID("10000000-0000-0000-0000-000000000002")


async def _run(args: argparse.Namespace) -> None:
    guard_rag_v02_split(args.split)
    if args.split != "dev":
        raise ValueError("M5D gate calibration runner executes only --split dev")
    cases = load_rag_v02_cases(ROOT / "evals/rag/v0.2/questions.jsonl")
    audit = audit_rag_v02(ROOT, cases=cases)
    dev_cases = tuple(case for case in cases if case.split == "dev")
    if len(dev_cases) != 96:
        raise ValueError("rag-v0.2 DEV must contain exactly 96 cases")
    if not args.database_url:
        raise ValueError("VERBAOPS_DATABASE__URL is required")
    if not args.reranker_url:
        raise ValueError("VERBAOPS_RAG__RERANKER_URL is required for G2 evaluation")

    evaluated_git_sha = require_committed_behavior(ROOT, pre_experiment_sha=PRE_EXPERIMENT_SHA)
    require_canonical_run_directory(ROOT, args.run_dir, run_id=args.run_id)
    args.run_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = args.run_dir / "gate_cases.jsonl"
    run_identity = {
        "benchmark_version": audit.dataset_version,
        "split": "dev",
        "dataset_sha256": audit.dataset_sha256,
        "knowledge_manifest_sha256": audit.knowledge_manifest_sha256,
        "experiment_plan_sha256": sha256_file(ROOT / "evals/rag/v0.2/experiment-plan.json"),
        "pre_experiment_sha": PRE_EXPERIMENT_SHA,
        "evaluated_git_sha": evaluated_git_sha,
        "evidence_gate": "CALIBRATE_ALL_PREREGISTERED_GATES",
        "evidence_gate_threshold": "calibration_sweep",
        "grounding_candidate": "NOT_APPLICABLE_GATE_CALIBRATION",
        "model_candidate": "NOT_APPLICABLE_GATE_CALIBRATION",
        "retrieval_profile_version": PRODUCTION_RETRIEVAL_PROFILE.version,
        "agent_prompt_version": "not_applicable_gate_calibration",
        "agent_graph_version": "not_applicable_gate_calibration",
        "model_revision": (
            f"{EMBEDDING_MODEL}@d128750597153bb5987e10b1c3493a34e5a4502a;"
            f"{RERANKER_MODEL}@1427fd652930e4ba29e8149678df786c240d8825"
        ),
        "run_id": args.run_id,
    }
    run_identity_digest = bind_checkpoint_identity(checkpoint_path, run_identity)
    expected_case_ids = {case.case_id for case in dev_cases}
    records = load_checkpoint_records(
        checkpoint_path, run_identity, expected_case_ids=expected_case_ids
    )
    for case_id, record in records.items():
        if set(record.get("gate_results", {})) != {gate.value for gate in EvidenceGate}:
            raise ValueError(f"incomplete M5D gate checkpoint record: {case_id}")
    engine = create_async_engine(args.database_url, pool_pre_ping=True, echo=False)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    llm_settings = LLMSettings(
        base_url=args.embedding_gateway_url,
        api_key=SecretStr(args.embedding_gateway_key or "m5d-local-gateway-key"),
        timeout_seconds=args.timeout_seconds,
    )
    try:
        async with httpx.AsyncClient(timeout=args.timeout_seconds) as client:
            embedding_client = EmbeddingClient(llm_settings, client)
            reranker_client = RerankerClient(
                args.reranker_url,
                client,
                timeout_seconds=args.timeout_seconds,
            )
            adapter = PostgresM5dGateAdapter(
                sessions,
                tenant_id=TENANT_ID,
                embedding_client=embedding_client,
                reranker_client=reranker_client,
            )
            with checkpoint_path.open("a", encoding="utf-8", newline="\n") as handle:
                for case in dev_cases:
                    if case.case_id in records:
                        continue
                    record = await adapter.execute(case)
                    record["run_id"] = args.run_id
                    record["run_identity_sha256"] = run_identity_digest
                    handle.write(json.dumps(record, sort_keys=True) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                    records[case.case_id] = record
    finally:
        await engine.dispose()

    if set(records) != {case.case_id for case in dev_cases}:
        raise ValueError("M5D gate evaluation did not complete all 96 DEV cases")
    observations_by_gate: dict[EvidenceGate, list[GateObservation]] = {
        gate: [] for gate in EvidenceGate
    }
    for case in dev_cases:
        record = records[case.case_id]
        for gate in EvidenceGate:
            raw_results = record.get("gate_results")
            if not isinstance(raw_results, dict):
                raise ValueError("gate checkpoint is missing candidate observations")
            result = raw_results.get(gate.value)
            if not isinstance(result, dict):
                raise ValueError("gate checkpoint is missing a candidate observation")
            observations_by_gate[gate].append(
                GateObservation(
                    case_id=case.case_id,
                    answerable=case.answerable,
                    confidence=result.get("confidence"),
                    latency_components_ms=result.get("latency_components_ms", {}),
                )
            )
    calibrations = [
        calibrate_evidence_gate(gate, observations)
        for gate, observations in observations_by_gate.items()
    ]
    selected = select_evidence_gate(calibrations)
    identity_path = checkpoint_path.with_name(f"{checkpoint_path.name}.identity.json")
    report_path = args.run_dir / "gate-report.json"
    output = {
        "run_id": args.run_id,
        "run_identity_sha256": run_identity_digest,
        "run_identity": run_identity,
        "evaluated_git_sha": evaluated_git_sha,
        "pre_experiment_sha": PRE_EXPERIMENT_SHA,
        "benchmark_version": audit.dataset_version,
        "split": "dev",
        "case_count": len(dev_cases),
        "dataset_sha256": audit.dataset_sha256,
        "knowledge_manifest_sha256": audit.knowledge_manifest_sha256,
        "experiment_plan_sha256": sha256_file(ROOT / "evals/rag/v0.2/experiment-plan.json"),
        "holdout_executed": False,
        "production_promoted": False,
        "artifacts": [
            artifact_reference(ROOT, checkpoint_path),
            artifact_reference(ROOT, identity_path),
        ],
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "gate_calibrations": [item.as_dict() for item in calibrations],
        "selected_gate": selected.as_dict() if selected is not None else None,
        "gate_status": (
            "GATE_SELECTED" if selected is not None else "NO_GATE_MEETS_90_PERCENT_NO_ANSWER_GUARD"
        ),
    }
    report_path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary_path = args.run_dir / "run-summary.json"
    summary = {
        "canonical": True,
        "run_id": args.run_id,
        "run_identity": run_identity,
        "run_identity_sha256": run_identity_sha256(run_identity),
        "evaluated_git_sha": evaluated_git_sha,
        "pre_experiment_sha": PRE_EXPERIMENT_SHA,
        "completed_cases": len(records),
        "artifacts": [
            artifact_reference(ROOT, checkpoint_path),
            artifact_reference(ROOT, identity_path),
            artifact_reference(ROOT, report_path),
        ],
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "completed_cases": len(records),
                "selected_gate": output["selected_gate"],
                "gate_status": output["gate_status"],
                "holdout_executed": False,
            },
            sort_keys=True,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="dev", choices=("dev", "release_holdout"))
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--database-url", default=os.environ.get("VERBAOPS_DATABASE__URL"))
    parser.add_argument(
        "--embedding-gateway-url",
        default=os.environ.get("VERBAOPS_LLM__BASE_URL", "http://localhost:14000/v1"),
    )
    parser.add_argument("--embedding-gateway-key", default=os.environ.get("VERBAOPS_LLM__API_KEY"))
    parser.add_argument(
        "--reranker-url",
        default=os.environ.get("VERBAOPS_RAG__RERANKER_URL", "http://localhost:8082"),
    )
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    args = parser.parse_args()
    try:
        asyncio.run(_run(args))
    except (OSError, ValueError, KeyError, httpx.HTTPError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
