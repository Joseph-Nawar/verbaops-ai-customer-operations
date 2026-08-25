"""Run the provider-free M4A evaluation harness."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from verbaops.agent.versions import GRAPH_VERSION, PROMPT_VERSION, TOOL_SCHEMA_VERSION
from verbaops.evaluation.cases import load_cases
from verbaops.evaluation.corpus import load_manifest
from verbaops.evaluation.models import EvaluationRunMetadata
from verbaops.evaluation.reports import render_console_summary
from verbaops.evaluation.repository import EvaluationRepository
from verbaops.evaluation.runner import DeterministicFixtureAdapter, run_evaluation

ROOT = Path(__file__).resolve().parents[1]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the deterministic VerbaOps text-agent evaluation harness")
    parser.add_argument("--adapter", choices=("deterministic",), default="deterministic")
    parser.add_argument("--cases", type=Path, default=ROOT / "evals/agent/v0.1/cases.jsonl")
    parser.add_argument("--manifest", type=Path, default=ROOT / "evals/agent/v0.1/manifest.json")
    parser.add_argument("--scenario-manifest", type=Path, default=ROOT / "tests/acceptance/fixtures/novacommerce-scenarios.json")
    parser.add_argument("--output-root", type=Path, default=ROOT / "artifacts/eval_runs")
    parser.add_argument("--database-url", default=os.environ.get("VERBAOPS_DATABASE__URL"))
    return parser


def _git_sha() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=False, capture_output=True, text=True
    )
    return completed.stdout.strip() if completed.returncode == 0 else "local"


async def _run(args: argparse.Namespace) -> int:
    cases = load_cases(args.cases)
    manifest = load_manifest(args.manifest)
    scenario_manifest = json.loads(args.scenario_manifest.read_text(encoding="utf-8"))
    run_id = uuid4()
    metadata = EvaluationRunMetadata(
        id=run_id,
        dataset_version=manifest.dataset_version,
        dataset_sha256="0" * 64,
        git_sha=_git_sha(),
        environment=os.environ.get("VERBAOPS_ENVIRONMENT", "local"),
        capability_alias="deterministic-fixture",
        prompt_version=PROMPT_VERSION,
        graph_version=GRAPH_VERSION,
        tool_schema_version=TOOL_SCHEMA_VERSION,
        case_count=len(cases),
        started_at=datetime.now(UTC),
    )
    adapter = DeterministicFixtureAdapter()
    if args.database_url:
        engine = create_async_engine(args.database_url, pool_pre_ping=True, echo=False)
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                summary = await run_evaluation(
                    tuple(cases),
                    adapter,
                    manifest=manifest,
                    scenario_manifest=scenario_manifest,
                    dataset_bytes=args.cases.read_bytes(),
                    output_root=args.output_root,
                    run_id=run_id,
                    metadata=metadata,
                    repository=EvaluationRepository(),
                    session=session,
                )
        finally:
            await engine.dispose()
    else:
        summary = await run_evaluation(
            tuple(cases),
            adapter,
            manifest=manifest,
            scenario_manifest=scenario_manifest,
            dataset_bytes=args.cases.read_bytes(),
            output_root=args.output_root,
            run_id=run_id,
            metadata=metadata,
        )
    print(render_console_summary(summary, args.output_root / str(summary.run_id)))
    return 0


def main() -> int:
    """Run the selected evaluation adapter."""

    return asyncio.run(_run(_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
