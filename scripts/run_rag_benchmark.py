"""Run the genuine PostgreSQL-backed Stage 5 RAG benchmark."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from verbaops.config.settings import LLMSettings
from verbaops.evaluation.rag_corpus import audit_rag_corpus, load_rag_cases
from verbaops.evaluation.rag_runner import (
    DEFAULT_PARAMETERS,
    RetrievalStrategy,
    calibrate_threshold,
    run_benchmark,
    score_benchmark_records,
    select_strategy,
    validate_holdout_provenance,
)
from verbaops.evaluation.rag_runtime import PostgresRagAdapter
from verbaops.knowledge.profiles import EMBEDDING_MODEL, EMBEDDING_PROFILE
from verbaops.retrieval.service import RERANKER_MODEL

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals/rag/v0.1/questions.jsonl"
SELECTION = ROOT / "evals/rag/v0.1/selection.json"
TEI_IMAGE_DIGEST = "sha256:c26a226262ad4ff3330fb30b76653c1bb65da2fcf413b92284545a010e0a8a48"
EMBEDDING_REVISION = "d128750597153bb5987e10b1c3493a34e5a4502a"
RERANKER_REVISION = "1427fd652930e4ba29e8149678df786c240d8825"
ALL_STRATEGIES = tuple(RetrievalStrategy)


def _git_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _selection_payload(
    audit: Any, metrics: dict[str, dict[str, Any]], decision: Any, calibration: Any
) -> dict[str, object]:
    return {
        "dataset_sha256": audit.dataset_sha256,
        "knowledge_manifest_sha256": audit.knowledge_manifest_sha256,
        "strategy": decision.strategy,
        "strategy_parameters": DEFAULT_PARAMETERS.as_dict(),
        "embedding_profile": EMBEDDING_PROFILE,
        "embedding_model": EMBEDDING_MODEL,
        "embedding_revision": EMBEDDING_REVISION,
        "reranker_model": RERANKER_MODEL,
        "reranker_revision": RERANKER_REVISION,
        "tei_image_digest": TEI_IMAGE_DIGEST,
        "dev_metrics": metrics,
        "selection_rationale": decision.rationale,
        "threshold_calibration": calibration.as_dict(),
        "calibrated_threshold": calibration.threshold,
        "git_sha": _git_sha(),
        "timestamp": datetime.now(UTC).isoformat(),
    }


async def _run(args: argparse.Namespace) -> None:
    cases = load_rag_cases(DATASET)
    audit = audit_rag_corpus(cases, ROOT)
    selected_cases = tuple(case for case in cases if case.split == args.split)
    selection: dict[str, object] | None = None
    if args.split == "release_holdout":
        if args.selection is None:
            raise ValueError("release_holdout requires --selection")
        selection = json.loads(args.selection.read_text(encoding="utf-8"))
        validate_holdout_provenance(
            selection,
            dataset_sha256=audit.dataset_sha256,
            knowledge_sha256=audit.knowledge_manifest_sha256,
        )
    if not args.database_url:
        raise ValueError("--database-url or VERBAOPS_DATABASE__URL is required")

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir or ROOT / "artifacts" / "rag_eval_runs" / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{args.split}-retrieval.jsonl"
    engine = create_async_engine(args.database_url, pool_pre_ping=True, echo=False)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with httpx.AsyncClient() as gateway_http, httpx.AsyncClient() as reranker_http:
            embedding_settings = LLMSettings(
                base_url=args.gateway_url,
                api_key=SecretStr(os.environ.get("VERBAOPS_LLM__API_KEY", "benchmark-local-key")),
            )
            from verbaops.knowledge.embeddings import EmbeddingClient
            from verbaops.retrieval.reranker import RerankerClient

            adapter = PostgresRagAdapter(
                sessions,
                tenant_id=UUID(args.tenant_id),
                embedding_client=EmbeddingClient(embedding_settings, gateway_http),
                reranker_client=RerankerClient(args.reranker_url, reranker_http),
            )
            await run_benchmark(
                selected_cases,
                strategies=ALL_STRATEGIES,
                adapter=adapter,
                output_path=output_path,
            )
    finally:
        await engine.dispose()

    all_records = [
        json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines() if line
    ]
    metrics = {
        strategy.value: score_benchmark_records(selected_cases, all_records, strategy).as_dict()
        for strategy in ALL_STRATEGIES
    }
    if args.split == "dev":
        if SELECTION.exists():
            raise ValueError(
                "selection.json already exists; refusing to overwrite frozen provenance"
            )
        decision = select_strategy(metrics)
        by_case = {
            str(record["case_id"]): record
            for record in all_records
            if record.get("strategy") == decision.strategy
        }
        observations = [
            (
                case.answerable,
                (
                    float(by_case[case.case_id]["top_confidence_score"])
                    if by_case[case.case_id].get("top_confidence_score") is not None
                    else None
                ),
            )
            for case in selected_cases
        ]
        calibration = calibrate_threshold(observations)
        payload = _selection_payload(audit, metrics, decision, calibration)
        SELECTION.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"audit": audit.model_dump(mode="json"), "selection": payload}, indent=2))
    else:
        print(
            json.dumps(
                {
                    "audit": audit.model_dump(mode="json"),
                    "split": args.split,
                    "metrics": metrics,
                    "selection": selection,
                    "raw_artifact": str(output_path),
                },
                indent=2,
                sort_keys=True,
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("dev", "release_holdout"), default="dev")
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--database-url", default=os.environ.get("VERBAOPS_DATABASE__URL"))
    parser.add_argument("--tenant-id", default="10000000-0000-0000-0000-000000000002")
    parser.add_argument(
        "--gateway-url",
        default=os.environ.get("VERBAOPS_LLM__BASE_URL", "http://localhost:14000/v1"),
    )
    parser.add_argument(
        "--reranker-url",
        default=os.environ.get("VERBAOPS_RAG__RERANKER_URL", "http://localhost:8082"),
    )
    args = parser.parse_args()
    try:
        asyncio.run(_run(args))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
