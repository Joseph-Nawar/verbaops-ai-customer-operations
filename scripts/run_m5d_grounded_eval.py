"""Resume one rag-v0.2 DEV grounding candidate over the public agent API."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from verbaops.evaluation.rag_grounding import run_grounded_evaluation, score_grounded_records
from verbaops.evaluation.rag_v02 import (
    audit_rag_v02,
    guard_rag_v02_split,
    load_rag_v02_cases,
    sha256_file,
)
from verbaops.evaluation.rag_v02_gates import EvidenceGate
from verbaops.evaluation.rag_v02_grounded_runtime import PublicRagV02AgentAdapter

ROOT = Path(__file__).resolve().parents[1]
GROUNDING_CANDIDATES = {
    "P0_CURRENT",
    "P1_PROMPT_V3",
    "P2_FAIL_CLOSED_CITATIONS",
    "P3_ONE_REPAIR_THEN_FAIL_CLOSED",
}


def _evaluation_provenance() -> dict[str, str | bool]:
    git_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    worktree_status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {"evaluated_git_sha": git_sha, "evaluation_worktree_dirty": bool(worktree_status)}


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

    args.run_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = args.run_dir / "grounded_cases.jsonl"
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
    provenance = _evaluation_provenance()
    try:
        async with httpx.AsyncClient(timeout=args.timeout_seconds) as client:
            adapter = PublicRagV02AgentAdapter(
                args.base_url,
                args.token,
                client,
                sessions,
                grounding_candidate=args.grounding,
                gate_threshold=args.threshold,
            )
            new_records = await run_grounded_evaluation(
                cases,
                adapter,
                checkpoint,
                secrets_to_hide=secrets_to_hide,
                delay_seconds_between_cases=args.inter_case_delay_seconds,
                record_metadata=provenance,
            )
    finally:
        await engine.dispose()
    records: list[dict[str, Any]] = [
        json.loads(line) for line in checkpoint.read_text(encoding="utf-8").splitlines() if line
    ]
    report = score_grounded_records(cases, records, args.threshold)
    costs = [float(record["cost_usd"]) for record in records if record.get("cost_usd") is not None]
    report["total_cost_usd_over_costed_observations"] = sum(costs) if costs else None
    report["mean_cost_usd_over_costed_observations"] = sum(costs) / len(costs) if costs else None
    report["cost_metadata_observations"] = len(costs)
    report["model_metadata"] = _metadata_summary(records)
    metadata = {
        "run_id": args.run_id,
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
    (args.run_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.run_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
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
    except (OSError, ValueError, KeyError, httpx.HTTPError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
