"""Run the real Stage 5 agent path with durable grounded-evaluation checkpoints."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from verbaops.evaluation.live import TraceReader
from verbaops.evaluation.rag_corpus import audit_rag_corpus, load_rag_cases
from verbaops.evaluation.rag_grounding import run_grounded_evaluation, score_grounded_records
from verbaops.evaluation.rag_runner import validate_holdout_provenance
from verbaops.knowledge.repository_tables import (
    knowledge_chunks,
    knowledge_documents,
    knowledge_versions,
    message_citations,
    retrieval_candidates,
    retrieval_invocations,
)

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals/rag/v0.1/questions.jsonl"


class PublicRagAgentAdapter:
    """Call the public API, then read only sanitized application-owned trace data."""

    def __init__(
        self,
        base_url: str,
        bearer_token: str,
        http_client: httpx.AsyncClient,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._bearer_token = bearer_token
        self._http_client = http_client
        self._sessions = sessions
        self._trace_reader = TraceReader(sessions)

    async def execute(self, case: Any) -> dict[str, Any]:
        started = datetime.now(UTC)
        headers = {"Authorization": f"Bearer {self._bearer_token}"}
        conversation = await self._http_client.post(
            f"{self._base_url}/v1/conversations", json={}, headers=headers
        )
        conversation.raise_for_status()
        conversation_id = UUID(str(conversation.json()["conversation_id"]))
        response = await self._http_client.post(
            f"{self._base_url}/v1/conversations/{conversation_id}/messages",
            json={"content": case.query},
            headers=headers,
        )
        response.raise_for_status()
        payload = response.json()
        run_id = UUID(str(payload["run_id"]))
        assistant = payload["assistant_message"]
        trace = await self._trace_reader.read(run_id)
        citation_rows = await self._citation_rows(UUID(str(assistant["id"])))
        invocation_ids = {
            row["retrieval_invocation_id"]
            for row in citation_rows
            if row["retrieval_invocation_id"]
        }
        evidence, top_score, invocation_id = await self._retrieval_rows(invocation_ids, run_id)
        costs = [call.cost_usd for call in trace.model_calls if call.cost_usd is not None]
        first_call = trace.model_calls[0] if trace.model_calls else None
        return {
            "final_answer": str(assistant["content"]),
            "public_citations": [_locator(row) for row in citation_rows],
            "selected_evidence": evidence,
            "top_confidence_score": top_score,
            "retrieval_invocation_id": str(invocation_id) if invocation_id else None,
            "agent_run_id": str(run_id),
            "answer_latency_ms": (datetime.now(UTC) - started).total_seconds() * 1000,
            "model": first_call.model if first_call else None,
            "provider": first_call.provider if first_call else None,
            "gateway_model_id": first_call.gateway_model_id if first_call else None,
            "capability_alias": first_call.capability_alias if first_call else None,
            "cost_usd": sum(costs) if costs else None,
            "status": trace.run.status,
        }

    async def _citation_rows(self, message_id: UUID) -> list[dict[str, Any]]:
        async with self._sessions() as session:
            result = await session.execute(
                sa.select(
                    message_citations,
                    knowledge_chunks.c.chunk_index.label("citation_chunk_index"),
                )
                .select_from(
                    message_citations.outerjoin(
                        knowledge_chunks, knowledge_chunks.c.id == message_citations.c.chunk_id
                    )
                )
                .where(message_citations.c.message_id == message_id)
                .order_by(message_citations.c.citation_ordinal)
            )
            return [dict(row) for row in result.mappings().all()]

    async def _retrieval_rows(
        self, invocation_ids: set[UUID], agent_run_id: UUID
    ) -> tuple[list[str], float | None, UUID | None]:
        async with self._sessions() as session:
            if invocation_ids:
                invocation = await session.execute(
                    sa.select(retrieval_invocations.c.id, retrieval_invocations.c.top_score).where(
                        retrieval_invocations.c.id == sorted(invocation_ids, key=str)[0]
                    )
                )
            else:
                invocation = await session.execute(
                    sa.select(retrieval_invocations.c.id, retrieval_invocations.c.top_score)
                    .where(retrieval_invocations.c.agent_run_id == agent_run_id)
                    .order_by(retrieval_invocations.c.sequence.desc())
                    .limit(1)
                )
            invocation_row = invocation.mappings().one_or_none()
            if invocation_row is None:
                return [], None, None
            invocation_id = invocation_row["id"]
            statement = (
                sa.select(
                    knowledge_documents.c.slug,
                    knowledge_versions.c.version,
                    knowledge_chunks.c.section,
                    knowledge_chunks.c.chunk_index,
                )
                .select_from(
                    retrieval_candidates.join(
                        knowledge_chunks, knowledge_chunks.c.id == retrieval_candidates.c.chunk_id
                    )
                    .join(
                        knowledge_versions, knowledge_versions.c.id == knowledge_chunks.c.version_id
                    )
                    .join(
                        knowledge_documents,
                        knowledge_documents.c.id == knowledge_versions.c.document_id,
                    )
                )
                .where(
                    retrieval_candidates.c.retrieval_invocation_id == invocation_id,
                    retrieval_candidates.c.selected.is_(True),
                )
                .order_by(retrieval_candidates.c.rrf_rank, retrieval_candidates.c.chunk_id)
            )
            rows = (await session.execute(statement)).mappings().all()
            return (
                [
                    f"{row['slug']}|{row['version']}|{row['section']}|{row['chunk_index']}"
                    for row in rows
                ],
                invocation_row["top_score"],
                invocation_id,
            )


def _locator(row: dict[str, Any]) -> str:
    chunk_index = row.get("citation_chunk_index")
    return f"{row['document_slug']}|{row['document_version']}|{row['section']}|{chunk_index or 0}"


async def _run(args: argparse.Namespace) -> None:
    cases = load_rag_cases(DATASET)
    audit = audit_rag_corpus(cases, ROOT)
    selection = json.loads(args.selection.read_text(encoding="utf-8"))
    validate_holdout_provenance(
        selection,
        dataset_sha256=audit.dataset_sha256,
        knowledge_sha256=audit.knowledge_manifest_sha256,
    )
    args.run_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = args.run_dir / "grounded_cases.jsonl"
    engine = create_async_engine(args.database_url, pool_pre_ping=True, echo=False)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with httpx.AsyncClient(timeout=args.timeout_seconds) as client:
            adapter = PublicRagAgentAdapter(args.base_url, args.token, client, sessions)
            await run_grounded_evaluation(cases, adapter, checkpoint)
    finally:
        await engine.dispose()
    records = [
        json.loads(line) for line in checkpoint.read_text(encoding="utf-8").splitlines() if line
    ]
    report = score_grounded_records(cases, records, float(selection["calibrated_threshold"]))
    metadata = {
        "dataset_version": audit.dataset_version,
        "dataset_sha256": audit.dataset_sha256,
        "knowledge_manifest_sha256": audit.knowledge_manifest_sha256,
        "selected_strategy": selection["strategy"],
        "calibrated_threshold": selection["calibrated_threshold"],
        "completed_case_count": len(records),
        "started_at": datetime.now(UTC).isoformat(),
        "credentials_persisted": False,
    }
    (args.run_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.run_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"metadata": metadata, "report": report}, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--database-url", default=os.environ.get("VERBAOPS_DATABASE__URL"))
    parser.add_argument(
        "--base-url", default=os.environ.get("VERBAOPS_AGENT_API_URL", "http://localhost:8000")
    )
    parser.add_argument("--token", default=os.environ.get("VERBAOPS_AUTH__DEVELOPMENT_TOKEN"))
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    args = parser.parse_args()
    if not args.database_url or not args.token:
        parser.error("--database-url and --token are required")
    try:
        asyncio.run(_run(args))
    except (OSError, ValueError, KeyError, httpx.HTTPError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
