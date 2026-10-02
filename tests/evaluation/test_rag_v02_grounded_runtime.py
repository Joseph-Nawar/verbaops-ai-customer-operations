from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from verbaops.agent.p4_grounding import finalize_p4_response
from verbaops.evaluation.live import TraceReader
from verbaops.evaluation.p4_trace import P4TraceStore
from verbaops.evaluation.p5_trace import P5TraceStore, project_p5_diagnostics
from verbaops.evaluation.rag_v02_grounded_runtime import PublicRagV02AgentAdapter
from verbaops.retrieval.grounding import CitationFinalizer


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
        "p4_extractive_mode_reason": "all_claims_rejected_safe_fallback",
        "tool_path_entered": False,
        "p4_extractive_mode_deactivated_after_tool": False,
        "raw_structured_model_response": '{"claims":[]}',
        "parse_success": True,
        "parse_failure_reason": None,
        "proposed_claims": [],
        "proposed_evidence_handle_per_claim": [],
        "proposed_excerpt_per_claim": [],
        "handle_validation_result_per_claim": [],
        "excerpt_validation_result_per_claim": [],
        "deterministic_rejection_reason_per_claim": [],
        "rendered_final_claims": "",
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


@pytest.mark.asyncio
async def test_p5_adapter_returns_p5_labelled_trace_reference_and_diagnostics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_uuid = UUID("00000000-0000-0000-0000-000000000021")
    conversation_id = "00000000-0000-0000-0000-000000000022"
    message_id = "00000000-0000-0000-0000-000000000023"
    canonical_run_id = "canonical-M0-P5-20261002T120000Z-1234abcd"

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
                    "run_id": str(run_uuid),
                    "assistant_message": {"id": message_id, "content": "A claim. [[K1]]"},
                }
            )

    run_directory = tmp_path / canonical_run_id
    trace_store = P5TraceStore(run_directory, canonical_run_id)
    diagnostics = project_p5_diagnostics(
        finalize_p4_response("{", [], CitationFinalizer()).diagnostics(),
        knowledge_mode_active=True,
        tool_path_entered=False,
    )
    trace_store.write(run_uuid, diagnostics)
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
        grounding_candidate="P5_PROMPT_JSON_EXTRACTIVE_SINGLE_PASS",
        gate_threshold=0.2554669,
        p5_trace_run_directory=run_directory,
        p5_trace_run_id=canonical_run_id,
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

    assert result["p5_diagnostics"] == diagnostics
    assert result["p5_trace_artifact"]["path"] == f"p5-traces/{run_uuid}.json"
    assert result["p5_trace_artifact"]["sha256"] == trace_store.read(run_uuid).sha256
