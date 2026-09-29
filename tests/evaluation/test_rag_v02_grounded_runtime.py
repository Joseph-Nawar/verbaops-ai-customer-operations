from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from verbaops.evaluation.rag_v02_grounded_runtime import PublicRagV02AgentAdapter


@pytest.mark.asyncio
async def test_p3_adapter_records_repair_trace_without_exposing_it_publicly() -> None:
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
        HTTPClient(),
        None,
        grounding_candidate="P3_ONE_REPAIR_THEN_FAIL_CLOSED",
        gate_threshold=0.4,
    )

    async def read_trace(_run_id: Any) -> Any:
        return trace

    async def citation_rows(_message_id: Any) -> list[dict[str, Any]]:
        return [
            {
                "document_slug": "returns-policy",
                "document_version": "2026.1",
                "section": "Return window",
                "citation_chunk_index": 1,
            }
        ]

    async def retrieval_rows(_run_id: Any) -> tuple[list[str], float]:
        return ["returns-policy|2026.1|Return window|1"], 0.5

    adapter._trace_reader.read = read_trace
    adapter._citation_rows = citation_rows
    adapter._retrieval_rows = retrieval_rows

    result = await adapter.execute(SimpleNamespace(query="question"))

    assert result["repair_attempted"] is True
    assert result["repair_succeeded"] is True
    assert result["repair_failed_reason"] is None
    assert result["repair_model_latency_ms"] == 250.0
    assert result["repair_cost_usd"] == 0.0005
    assert result["tool_call_count"] == 0
    assert "repair_attempted" not in result["final_answer"]
