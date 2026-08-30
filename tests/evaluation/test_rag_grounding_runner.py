from pathlib import Path
from typing import Any, cast

import pytest

from verbaops.evaluation.rag_corpus import load_rag_cases
from verbaops.evaluation.rag_grounding import (
    GroundedExecutionAdapter,
    run_grounded_evaluation,
    score_grounded_records,
)

ROOT = Path(__file__).parents[2]


@pytest.mark.asyncio
async def test_grounded_runner_resumes_completed_cases_and_sanitizes_credentials(
    tmp_path: Path,
) -> None:
    case = load_rag_cases(ROOT / "evals/rag/v0.1/questions.jsonl")[0]
    output = tmp_path / "grounded.jsonl"
    output.write_text('{"case_id":"' + case.case_id + '","status":"completed"}\n', encoding="utf-8")

    class Adapter:
        async def execute(self, _case: Any) -> dict[str, object]:
            raise AssertionError("completed case must be skipped")

    assert await run_grounded_evaluation((case,), Adapter(), output) == []

    class CredentialAdapter:
        async def execute(self, _case: Any) -> dict[str, object]:
            return {
                "final_answer": "answer",
                "public_citations": [],
                "selected_evidence": [],
                "agent_run_id": "run-2",
                "api_key": "must-not-persist",
                "metadata": {"provider": "test", "access_token": "must-not-persist"},
            }

    case_two = load_rag_cases(ROOT / "evals/rag/v0.1/questions.jsonl")[1]
    records = await run_grounded_evaluation((case_two,), CredentialAdapter(), output)
    assert len(records) == 1
    serialized = output.read_text(encoding="utf-8")
    assert "must-not-persist" not in serialized
    assert "api_key" not in serialized
    assert "access_token" not in serialized


@pytest.mark.asyncio
async def test_grounded_runner_rejects_duplicate_checkpoint_case_ids(tmp_path: Path) -> None:
    case = load_rag_cases(ROOT / "evals/rag/v0.1/questions.jsonl")[0]
    output = tmp_path / "grounded.jsonl"
    line = '{"case_id":"' + case.case_id + '","status":"completed"}\n'
    output.write_text(line + line, encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate grounded checkpoint"):
        await run_grounded_evaluation((case,), cast(GroundedExecutionAdapter, object()), output)


def test_grounded_scoring_uses_only_labeled_facts_and_inclusive_threshold() -> None:
    case = load_rag_cases(ROOT / "evals/rag/v0.1/questions.jsonl")[0]
    locator = "shipping-policy|2026.1|Delivery methods|1"
    result = score_grounded_records(
        (case,),
        (
            {
                "case_id": case.case_id,
                "final_answer": "Three to five business days.",
                "public_citations": [locator],
                "top_confidence_score": 0.5,
                "answer_latency_ms": 12.0,
                "cost_usd": 0.01,
            },
        ),
        threshold=0.5,
    )
    assert result["citation_precision"]["value"] == 1.0
    assert result["groundedness"]["value"] == 1.0
    assert result["unsupported_claim_rate"] == 0.0
    assert result["abstention_accuracy"]["value"] == 1.0
    assert result["cost_metadata_coverage"]["value"] == 1.0
