from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from verbaops.evaluation.live import TraceReader
from verbaops.evaluation.p4_trace import P4TraceStore
from verbaops.evaluation.rag_v02_grounded_runtime import PublicRagV02AgentAdapter


@pytest.mark.asyncio
async def test_p3_adapter_records_repair_trace_without_exposing_it_publicly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "00000000-0000-0000-0000-000000000001"
    conversation_id = "00000000-0000-0000-0000-000000000002"
    message_id = "00000000-0000-0000-0000-000000000003"

    class Response:
        def __init__(self, payload: dict[str, Any]) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return self.payload

    class HTTPClient:
        async def post(self, url: str, **_kwargs: Any) -> Response:
            if url.endswith("/v1/conversations"):
                return Response({"conversation_id": conversation_id})
            return Response(
                {
                    "run_id": run_id,
                    "assistant_message": {
                        "id": message_id,
                        "content": "The return window is 30 days. [[K1]]",
                    },
                }
            )

    original_call = SimpleNamespace(
        model="groq/openai/gpt-oss-120b",
        provider=None,
        gateway_model_id="gateway-model-id",
        capability_alias="agent-fast",
        cost_usd=0.001,
        status="succeeded",
        latency_ms=500.0,
    )
    repair_call = SimpleNamespace(
        model="groq/openai/gpt-oss-120b",
        provider=None,
        gateway_model_id="gateway-model-id",
        capability_alias="agent-fast",
        cost_usd=0.0005,
        status="succeeded",
        latency_ms=250.0,
    )
    trace = SimpleNamespace(
        model_calls=(original_call, repair_call),
        tool_invocations=(),
        run=SimpleNamespace(status="completed"),
    )
    adapter = PublicRagV02AgentAdapter(
        "http://localhost:8000",
        "development-token",
        cast(httpx.AsyncClient, HTTPClient()),
        cast(async_sessionmaker[AsyncSession], object()),
        grounding_candidate="P3_ONE_REPAIR_THEN_FAIL_CLOSED",
        gate_threshold=0.4,
    )

    async def read_trace(_run_id: UUID) -> Any:
        return trace

    async def citation_rows(_message_id: UUID) -> list[dict[str, Any]]:
        return [
            {
                "document_slug": "returns-policy",
                "document_version": "2026.1",
                "section": "Return window",
                "citation_chunk_index": 1,
            }
        ]

    async def retrieval_rows(_run_id: UUID) -> tuple[list[str], float]:
        return ["returns-policy|2026.1|Return window|1"], 0.5

    monkeypatch.setattr(
        adapter, "_trace_reader", cast(TraceReader, SimpleNamespace(read=read_trace))
    )
    monkeypatch.setattr(adapter, "_citation_rows", citation_rows)
    monkeypatch.setattr(adapter, "_retrieval_rows", retrieval_rows)

    result = await adapter.execute(SimpleNamespace(query="question"))

    assert result["repair_attempted"] is True
    assert result["repair_succeeded"] is True
    assert result["repair_failed_reason"] is None
    assert result["repair_model_latency_ms"] == 250.0
    assert result["repair_cost_usd"] == 0.0005
    assert result["tool_call_count"] == 0
    assert "repair_attempted" not in result["final_answer"]


@pytest.mark.asyncio
async def test_p4_adapter_binds_sidecar_payload_and_hash_to_agent_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_id = UUID("00000000-0000-0000-0000-000000000011")
    conversation_id = "00000000-0000-0000-0000-000000000012"
    message_id = "00000000-0000-0000-0000-000000000013"
    canonical_run_id = "canonical-p4-adapter"

    class Response:
        def __init__(self, payload: dict[str, Any]) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return self.payload

    class HTTPClient:
        async def post(self, url: str, **_kwargs: Any) -> Response:
            if url.endswith("/v1/conversations"):
                return Response({"conversation_id": conversation_id})
            return Response(
                {
                    "run_id": str(run_id),
                    "assistant_message": {"id": message_id, "content": "A verified claim. [1]"},
                }
            )

    run_directory = tmp_path / canonical_run_id
    trace_store = P4TraceStore(run_directory, canonical_run_id)
    diagnostics = {
        "p4_extractive_mode_active": True,
        "p4_extractive_mode_reason": "selected_evidence_no_tool_path",
        "tool_path_entered": False,
        "p4_extractive_mode_deactivated_after_tool": False,
        "raw_structured_response": '{"claims":[]}',
        "parse_success": True,
        "parse_failure_reason": None,
        "proposed_claims": [],
        "claim_validation": [],
        "accepted_claims": [],
        "rendered_claims": "",
        "final_rendered_answer": "I'm unable to verify that information from the available company knowledge.",
        "fallback_used": True,
        "fallback_reason": "all_claims_rejected",
    }
    trace_store.write(run_id, diagnostics)
    call = SimpleNamespace(
        model="groq/openai/gpt-oss-120b",
        provider="groq",
        gateway_model_id="groq/openai/gpt-oss-120b",
        capability_alias="agent-fast",
        cost_usd=0.001,
        status="succeeded",
        latency_ms=500.0,
    )
    trace = SimpleNamespace(
        model_calls=(call,), tool_invocations=(), run=SimpleNamespace(status="completed")
    )
    adapter = PublicRagV02AgentAdapter(
        "http://localhost:8000",
        "development-token",
        cast(httpx.AsyncClient, HTTPClient()),
        cast(async_sessionmaker[AsyncSession], object()),
        grounding_candidate="P4_EVIDENCE_LINKED_SINGLE_PASS",
        gate_threshold=0.2554669,
        p4_trace_run_directory=run_directory,
        p4_trace_run_id=canonical_run_id,
    )

    async def read_trace(_run_id: UUID) -> Any:
        return trace

    async def citation_rows(_message_id: UUID) -> list[dict[str, Any]]:
        return []

    async def retrieval_rows(_run_id: UUID) -> tuple[list[str], float]:
        return ["returns-policy|2026.1|Returns|1"], 0.5

    monkeypatch.setattr(
        adapter, "_trace_reader", cast(TraceReader, SimpleNamespace(read=read_trace))
    )
    monkeypatch.setattr(adapter, "_citation_rows", citation_rows)
    monkeypatch.setattr(adapter, "_retrieval_rows", retrieval_rows)

    result = await adapter.execute(SimpleNamespace(query="What is the return window?"))

    assert result["p4_diagnostics"] == diagnostics
    assert result["p4_trace_artifact"]["path"] == f"p4-traces/{run_id}.json"
    assert result["p4_trace_artifact"]["sha256"] == trace_store.read(run_id).sha256
