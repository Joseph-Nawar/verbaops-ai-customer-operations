"""Sanitized public-API and trace adapter for rag-v0.2 DEV grounding runs."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from verbaops.evaluation.live import TraceReader
from verbaops.evaluation.p4_trace import P4TraceStore
from verbaops.knowledge.repository_tables import (
    knowledge_chunks,
    knowledge_documents,
    knowledge_versions,
    message_citations,
    retrieval_candidates,
    retrieval_invocations,
)
from verbaops.retrieval.grounding import SAFE_GROUNDING_FALLBACK


class PublicRagV02AgentAdapter:
    """Execute each case through the running public API and read owned traces."""

    def __init__(
        self,
        base_url: str,
        bearer_token: str,
        http_client: httpx.AsyncClient,
        sessions: async_sessionmaker[AsyncSession],
        *,
        grounding_candidate: str,
        gate_threshold: float,
        p4_trace_run_directory: Path | None = None,
        p4_trace_run_id: str | None = None,
    ) -> None:
        is_p4 = grounding_candidate == "P4_EVIDENCE_LINKED_SINGLE_PASS"
        if is_p4 != (p4_trace_run_directory is not None and p4_trace_run_id is not None):
            raise ValueError("P4 adapter requires an explicitly configured trace run")
        if (p4_trace_run_directory is None) != (p4_trace_run_id is None):
            raise ValueError("P4 trace directory and run ID must be configured together")
        self._base_url = base_url.rstrip("/")
        self._bearer_token = bearer_token
        self._http_client = http_client
        self._sessions = sessions
        self._grounding_candidate = grounding_candidate
        self._gate_threshold = gate_threshold
        self._p4_trace_store = (
            P4TraceStore(p4_trace_run_directory, p4_trace_run_id)
            if p4_trace_run_directory is not None and p4_trace_run_id is not None
            else None
        )
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
        selected_evidence, top_score = await self._retrieval_rows(run_id)
        tool_call_count = len(trace.tool_invocations)
        accepted_evidence = (
            top_score is not None and top_score >= self._gate_threshold and bool(selected_evidence)
        )
        repair_call = trace.model_calls[-1] if len(trace.model_calls) > 1 else None
        repair_attempted = bool(
            self._grounding_candidate == "P3_ONE_REPAIR_THEN_FAIL_CLOSED"
            and accepted_evidence
            and tool_call_count == 0
            and repair_call is not None
        )
        repair_succeeded = bool(
            repair_attempted
            and citation_rows
            and str(assistant["content"]).strip() != SAFE_GROUNDING_FALLBACK
        )
        repair_failed_reason = None
        if repair_attempted and not repair_succeeded:
            repair_failed_reason = (
                "model_call_failed"
                if repair_call is not None and repair_call.status == "failed"
                else "no_acceptable_repaired_answer"
            )
        costs = [call.cost_usd for call in trace.model_calls if call.cost_usd is not None]
        first_call = trace.model_calls[0] if trace.model_calls else None
        result = {
            "final_answer": str(assistant["content"]),
            "public_citations": [_citation_locator(row) for row in citation_rows],
            "selected_evidence": selected_evidence,
            "top_confidence_score": top_score,
            "agent_run_id": str(run_id),
            "answer_latency_ms": (datetime.now(UTC) - started).total_seconds() * 1000,
            "model": first_call.model if first_call else None,
            "provider": first_call.provider if first_call else None,
            "gateway_model_id": first_call.gateway_model_id if first_call else None,
            "capability_alias": first_call.capability_alias if first_call else None,
            "cost_usd": sum(costs) if costs else None,
            "cost_observations": len(costs),
            "model_call_count": len(trace.model_calls),
            "tool_call_count": tool_call_count,
            "repair_attempted": repair_attempted,
            "repair_succeeded": repair_succeeded,
            "repair_failed_reason": repair_failed_reason,
            "repair_model_latency_ms": (
                repair_call.latency_ms if repair_attempted and repair_call is not None else None
            ),
            "repair_cost_usd": (
                repair_call.cost_usd if repair_attempted and repair_call is not None else None
            ),
            "status": trace.run.status,
        }
        if self._p4_trace_store is not None:
            p4_artifact = self._p4_trace_store.read(run_id)
            result["p4_diagnostics"] = p4_artifact.payload["diagnostics"]
            result["p4_trace_artifact"] = {
                "path": p4_artifact.relative_path,
                "sha256": p4_artifact.sha256,
            }
        return result

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

    async def _retrieval_rows(self, agent_run_id: UUID) -> tuple[list[str], float | None]:
        async with self._sessions() as session:
            invocation = await session.execute(
                sa.select(retrieval_invocations.c.id, retrieval_invocations.c.top_score)
                .where(retrieval_invocations.c.agent_run_id == agent_run_id)
                .order_by(retrieval_invocations.c.sequence.desc())
                .limit(1)
            )
            invocation_row = invocation.mappings().one_or_none()
            if invocation_row is None:
                return [], None
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
                        knowledge_versions,
                        knowledge_versions.c.id == knowledge_chunks.c.version_id,
                    )
                    .join(
                        knowledge_documents,
                        knowledge_documents.c.id == knowledge_versions.c.document_id,
                    )
                )
                .where(
                    retrieval_candidates.c.retrieval_invocation_id == invocation_row["id"],
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
            )


def _citation_locator(row: dict[str, Any]) -> str:
    return (
        f"{row['document_slug']}|{row['document_version']}|{row['section']}|"
        f"{row.get('citation_chunk_index') or 0}"
    )


__all__ = ["PublicRagV02AgentAdapter"]
