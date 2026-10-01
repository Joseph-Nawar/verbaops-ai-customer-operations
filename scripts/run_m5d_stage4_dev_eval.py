"""Run only the existing Stage 4 DEV cases against one M5D grounding candidate."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from verbaops.evaluation.cases import load_cases
from verbaops.evaluation.corpus import CorpusManifest, audit_corpus
from verbaops.evaluation.live import LiveEvaluationAdapter, TraceReader
from verbaops.evaluation.metrics import aggregate_results, score_case
from verbaops.evaluation.models import CaseEvaluationResult, EvaluationObservation

ROOT = Path(__file__).resolve().parents[1]
CASES_FILE = ROOT / "evals/agent/v0.1/cases.jsonl"
MANIFEST_FILE = ROOT / "evals/agent/v0.1/manifest.json"
SCENARIO_FILE = ROOT / "tests/acceptance/fixtures/novacommerce-scenarios.json"
GROUNDING_CANDIDATES = {
    "P0_CURRENT",
    "P1_PROMPT_V3",
    "P2_FAIL_CLOSED_CITATIONS",
    "P3_ONE_REPAIR_THEN_FAIL_CLOSED",
    "P4_EVIDENCE_LINKED_SINGLE_PASS",
}


def _read_checkpoint(path: Path, expected_context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return records
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            value = json.loads(line)
            case_id = str(value["case_id"])
            if value.get("context") != expected_context or case_id in records:
                raise ValueError("duplicate or mismatched Stage 4 DEV checkpoint")
            CaseEvaluationResult.model_validate(value["result"])
            records[case_id] = value
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise ValueError(f"invalid Stage 4 DEV checkpoint line {line_number}") from error
    return records


async def _run(args: argparse.Namespace) -> None:
    if args.split != "dev":
        raise ValueError("M5D Stage 4 comparison executes only --split dev")
    if args.grounding not in GROUNDING_CANDIDATES:
        raise ValueError("grounding candidate is not preregistered")
    if args.model_candidate != "M0":
        raise ValueError("Stage 4 comparison runs the incumbent M0 only")
    if args.grounding == "P4_EVIDENCE_LINKED_SINGLE_PASS" and (
        args.gate != "G2_TOP_EVIDENCE_CROSS_ENCODER" or args.threshold != 0.2554669
    ):
        raise ValueError("P4 requires the frozen G2 gate and threshold")
    if not args.database_url or not args.token:
        raise ValueError("database and public API bearer token are required")

    manifest = CorpusManifest.model_validate_json(MANIFEST_FILE.read_text(encoding="utf-8"))
    all_cases = load_cases(CASES_FILE)
    dataset_sha256 = hashlib.sha256(CASES_FILE.read_bytes()).hexdigest()
    scenario_manifest = json.loads(SCENARIO_FILE.read_text(encoding="utf-8"))
    audit_corpus(manifest, all_cases, scenario_manifest)
    cases = tuple(case for case in all_cases if case.split == "dev")
    if len(cases) != 96:
        raise ValueError("Stage 4 DEV corpus must contain exactly 96 cases")

    context = {
        "dataset_version": manifest.dataset_version,
        "dataset_sha256": dataset_sha256,
        "split": "dev",
        "grounding_candidate": args.grounding,
        "model_candidate": args.model_candidate,
        "gate": args.gate,
        "threshold": args.threshold,
    }
    args.run_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = args.run_dir / "stage4_dev_cases.jsonl"
    records = _read_checkpoint(checkpoint, context)
    engine = create_async_engine(args.database_url, pool_pre_ping=True, echo=False)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    secret_values = tuple(
        value
        for value in (
            os.environ.get("VERBAOPS_AGENT_FAST_API_KEY", ""),
            os.environ.get("NOVACOMMERCE_SERVICE_TOKEN", ""),
            args.token,
        )
        if value
    )
    try:
        async with httpx.AsyncClient(
            base_url=args.base_url, timeout=args.timeout_seconds
        ) as client:
            adapter = LiveEvaluationAdapter(
                args.base_url,
                args.token,
                TraceReader(sessions),
                client,
                secret_values=secret_values,
            )
            with checkpoint.open("a", encoding="utf-8", newline="\n") as handle:
                for case in cases:
                    if case.case_id in records:
                        continue
                    observation = await adapter.observe(case)
                    result = score_case(case, observation)
                    serialized = json.dumps(
                        {
                            "case_id": case.case_id,
                            "context": context,
                            "result": result.model_dump(mode="json"),
                            "observation": {
                                "capability_alias": observation.capability_alias,
                                "gateway_model_id": observation.gateway_model_id,
                                "model": observation.model,
                                "provider": observation.provider,
                                "latency_ms": observation.latency_ms,
                                "cost_usd": observation.cost_usd,
                                "agent_run_id": str(observation.agent_run_id)
                                if observation.agent_run_id
                                else None,
                            },
                        },
                        sort_keys=True,
                    )
                    if any(secret in serialized for secret in secret_values):
                        raise ValueError(f"{case.case_id}: secret detected before checkpoint write")
                    handle.write(serialized + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                    records[case.case_id] = json.loads(serialized)
    finally:
        await engine.dispose()

    if set(records) != {case.case_id for case in cases}:
        raise ValueError("Stage 4 DEV run did not complete all 96 cases")
    results = [
        CaseEvaluationResult.model_validate(records[case.case_id]["result"]) for case in cases
    ]
    observations = [
        EvaluationObservation.model_validate(records[case.case_id]["observation"]) for case in cases
    ]
    summary = aggregate_results(results, observations).model_dump(mode="json")
    summary["overall_metrics"] = {
        key: value.model_dump(mode="json")
        for key, value in aggregate_results(results, observations).overall_metrics.items()
    }
    report = {
        "dataset_version": manifest.dataset_version,
        "dataset_sha256": dataset_sha256,
        "split": "dev",
        "case_count": len(cases),
        "model_candidate": args.model_candidate,
        "grounding_candidate": args.grounding,
        "gate": args.gate,
        "threshold": args.threshold,
        "holdout_executed": False,
        "summary": summary,
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "model_metadata": _model_metadata(records),
        "zero_unauthorized_actions": summary["overall_metrics"]["unauthorized_action_rate"][
            "numerator"
        ]
        == 0,
        "zero_s4_violations": summary["overall_metrics"]["critical_safety_violation_rate"][
            "numerator"
        ]
        == 0,
        "valid_tool_arguments": summary["overall_metrics"]["argument_all_fields_accuracy"]["value"]
        in (1.0, None),
    }
    (args.run_dir / "stage4-dev-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "case_count": len(cases),
                "split": "dev",
                "holdout_executed": False,
                "tool_selection_accuracy": summary["overall_metrics"]["tool_selection_accuracy"],
                "task_completion_rate": summary["overall_metrics"]["task_completion_rate"],
                "unauthorized_action_rate": summary["overall_metrics"]["unauthorized_action_rate"],
                "critical_safety_violation_rate": summary["overall_metrics"][
                    "critical_safety_violation_rate"
                ],
                "valid_tool_arguments": report["valid_tool_arguments"],
            },
            sort_keys=True,
        )
    )


def _model_metadata(records: Mapping[str, dict[str, Any]]) -> dict[str, object]:
    observations = [record["observation"] for record in records.values()]
    return {
        "models": sorted({str(item["model"]) for item in observations if item.get("model")}),
        "providers": sorted(
            {str(item["provider"]) for item in observations if item.get("provider")}
        ),
        "capability_aliases": sorted(
            {str(item["capability_alias"]) for item in observations if item.get("capability_alias")}
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", default="dev", choices=("dev", "release_holdout"))
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--database-url", default=os.environ.get("VERBAOPS_DATABASE__URL"))
    parser.add_argument(
        "--base-url", default=os.environ.get("VERBAOPS_AGENT_API_URL", "http://localhost:8000")
    )
    parser.add_argument("--token", default=os.environ.get("VERBAOPS_AUTH__DEVELOPMENT_TOKEN"))
    parser.add_argument("--grounding", required=True)
    parser.add_argument("--model-candidate", default="M0")
    parser.add_argument("--gate", required=True)
    parser.add_argument("--threshold", type=float, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    args = parser.parse_args()
    try:
        asyncio.run(_run(args))
    except (OSError, ValueError, KeyError, httpx.HTTPError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
