import json
from pathlib import Path
from typing import Any, cast

import pytest

from verbaops.evaluation import rag_grounding
from verbaops.evaluation.rag_corpus import load_rag_cases
from verbaops.evaluation.rag_grounding import (
    GroundedExecutionAdapter,
    run_grounded_evaluation,
    score_grounded_records,
)
from verbaops.evaluation.rag_models import RagCase, RelevanceJudgment
from verbaops.retrieval.grounding import SAFE_GROUNDING_FALLBACK

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
async def test_grounded_runner_redacts_configured_provider_secret_values(tmp_path: Path) -> None:
    case = load_rag_cases(ROOT / "evals/rag/v0.1/questions.jsonl")[0]
    output = tmp_path / "grounded.jsonl"

    class ProviderSecretAdapter:
        async def execute(self, _case: Any) -> dict[str, object]:
            return {"final_answer": "model echoed groq-secret-material"}

    await run_grounded_evaluation(
        (case,),
        ProviderSecretAdapter(),
        output,
        secrets_to_hide=("groq-secret-material",),
    )

    saved = output.read_text(encoding="utf-8")
    assert "groq-secret-material" not in saved
    assert "[redacted]" in saved


@pytest.mark.asyncio
async def test_grounded_runner_rejects_duplicate_checkpoint_case_ids(tmp_path: Path) -> None:
    case = load_rag_cases(ROOT / "evals/rag/v0.1/questions.jsonl")[0]
    output = tmp_path / "grounded.jsonl"
    line = '{"case_id":"' + case.case_id + '","status":"completed"}\n'
    output.write_text(line + line, encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate grounded checkpoint"):
        await run_grounded_evaluation((case,), cast(GroundedExecutionAdapter, object()), output)


@pytest.mark.asyncio
async def test_grounded_runner_waits_between_new_requests_only(tmp_path: Path, monkeypatch) -> None:
    cases = load_rag_cases(ROOT / "evals/rag/v0.1/questions.jsonl")[:3]
    output = tmp_path / "grounded.jsonl"
    output.write_text(
        json.dumps({"case_id": cases[0].case_id, "status": "completed"}) + "\n",
        encoding="utf-8",
    )
    events: list[tuple[str, str | float]] = []

    class Adapter:
        async def execute(self, case: RagCase) -> dict[str, object]:
            events.append(("execute", case.case_id))
            return {"final_answer": "answer"}

    async def fake_sleep(delay_seconds: float) -> None:
        events.append(("sleep", delay_seconds))

    monkeypatch.setattr(rag_grounding.asyncio, "sleep", fake_sleep)

    await run_grounded_evaluation(
        cases,
        Adapter(),
        output,
        delay_seconds_between_cases=12.0,
    )

    assert events == [
        ("execute", cases[1].case_id),
        ("sleep", 12.0),
        ("execute", cases[2].case_id),
    ]


@pytest.mark.asyncio
async def test_grounded_runner_records_evaluation_provenance_per_case(tmp_path: Path) -> None:
    case = load_rag_cases(ROOT / "evals/rag/v0.1/questions.jsonl")[0]

    class Adapter:
        async def execute(self, _case: RagCase) -> dict[str, object]:
            return {"final_answer": "answer"}

    records = await run_grounded_evaluation(
        (case,),
        Adapter(),
        tmp_path / "grounded.jsonl",
        record_metadata={
            "evaluated_git_sha": "44034e47119ec63c23f3abf4adcee20cac08ce4b",
            "evaluation_worktree_dirty": False,
        },
    )

    assert records[0]["evaluated_git_sha"] == "44034e47119ec63c23f3abf4adcee20cac08ce4b"
    assert records[0]["evaluation_worktree_dirty"] is False


def test_grounded_scoring_uses_labeled_facts_and_retrieval_evidence_gate() -> None:
    cases = load_rag_cases(ROOT / "evals/rag/v0.1/questions.jsonl")
    case = cases[0]
    no_answer_case = next(item for item in cases if not item.answerable)
    locator = "shipping-policy|2026.1|Delivery methods|1"
    result = score_grounded_records(
        (case, no_answer_case),
        (
            {
                "case_id": case.case_id,
                "final_answer": "Three to five business days. I cannot answer that.",
                "public_citations": [locator],
                "top_confidence_score": 0.5,
                "answer_latency_ms": 12.0,
                "cost_usd": 0.01,
            },
            {
                "case_id": no_answer_case.case_id,
                "final_answer": "Here is an answer despite no supporting evidence.",
                "public_citations": [],
                "top_confidence_score": 0.49,
                "cost_usd": 0.02,
            },
        ),
        threshold=0.5,
    )
    assert result["citation_precision"]["value"] == 1.0
    assert result["groundedness"]["value"] == 1.0
    assert result["unsupported_claim_rate"] == 0.0
    assert result["retrieval_evidence_gate_accuracy"] == {
        "numerator": 2,
        "denominator": 2,
        "value": 1.0,
    }
    assert result["cost_metadata_coverage"]["value"] == 1.0


def _citation_case(
    case_id: str, *, answerable: bool, judgments: tuple[RelevanceJudgment, ...]
) -> RagCase:
    return RagCase(
        case_id=case_id,
        dataset_version="rag-v0.1",
        split="dev",
        language="en",
        category="shipping" if answerable else "no-answer",
        query=case_id,
        answerable=answerable,
        expected_answer="answer" if answerable else "No supported answer.",
        relevance_judgments=judgments,
        expected_facts=(),
    )


def test_grounded_citation_precision_is_scoped_to_emitting_case() -> None:
    locator = RelevanceJudgment(
        document_slug="shipping-policy",
        document_version="2026.1",
        section="Delivery methods",
        chunk_index=1,
        relevance_grade=2,
    )
    case_a = _citation_case("case-a", answerable=True, judgments=(locator,))
    case_b = _citation_case("case-b", answerable=False, judgments=())
    result = score_grounded_records(
        (case_a, case_b),
        (
            {
                "case_id": "case-a",
                "final_answer": "answer",
                "public_citations": ["shipping-policy|2026.1|Delivery methods|1"],
            },
            {
                "case_id": "case-b",
                "final_answer": "answer",
                "public_citations": [
                    "shipping-policy|2026.1|Delivery methods|1",
                    "shipping-policy|2026.1|Delivery methods|1",
                ],
            },
        ),
        threshold=0.0,
    )
    assert result["citation_precision"] == {"numerator": 1, "denominator": 3, "value": 1 / 3}


def test_grounded_citation_precision_has_explicit_zero_denominator() -> None:
    case = _citation_case("case-a", answerable=False, judgments=())
    result = score_grounded_records(
        (case,),
        ({"case_id": "case-a", "final_answer": "No supported answer.", "public_citations": []},),
        threshold=0.0,
    )
    assert result["citation_precision"] == {"numerator": 0, "denominator": 0, "value": None}


def test_grounded_metrics_report_evidence_citation_compliance_and_fallbacks() -> None:
    locator = "shipping-policy|2026.1|Delivery methods|1"
    supported = _citation_case(
        "case-supported",
        answerable=True,
        judgments=(
            RelevanceJudgment(
                document_slug="shipping-policy",
                document_version="2026.1",
                section="Delivery methods",
                chunk_index=1,
                relevance_grade=2,
            ),
        ),
    )
    refused = _citation_case("case-refused", answerable=False, judgments=())

    result = score_grounded_records(
        (supported, refused),
        (
            {
                "case_id": supported.case_id,
                "final_answer": "Supported answer.",
                "public_citations": [locator],
                "selected_evidence": [locator],
                "top_confidence_score": 0.5,
                "tool_call_count": 0,
                "repair_attempted": False,
                "repair_succeeded": False,
            },
            {
                "case_id": refused.case_id,
                "final_answer": SAFE_GROUNDING_FALLBACK,
                "public_citations": [],
                "selected_evidence": [],
                "top_confidence_score": 0.1,
                "tool_call_count": 0,
                "repair_attempted": True,
                "repair_succeeded": False,
                "repair_failed_reason": "no_acceptable_repaired_answer",
                "repair_model_latency_ms": 40.0,
                "repair_cost_usd": 0.01,
            },
        ),
        threshold=0.4,
    )

    assert result["accepted_evidence_citation_compliance"] == {
        "numerator": 1,
        "denominator": 1,
        "value": 1.0,
    }
    assert result["safe_fallback_count"] == 1
    assert result["safe_fallback_rate"] == 0.5
    assert result["repair_attempts"] == 1
    assert result["repair_successes"] == 0
    assert result["repair_failures"] == 1
    assert result["repair_model_latency_p50_ms"] == 40.0
    assert result["repair_cost_total_usd"] == 0.01
