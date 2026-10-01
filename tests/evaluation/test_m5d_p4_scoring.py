"""P4-only scorer-v2 integration; historical scoring remains a separate path."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import verbaops.evaluation.rag_grounding as rag_grounding
from verbaops.evaluation.rag_grounding import score_grounded_records, score_p4_grounded_records
from verbaops.evaluation.rag_v02 import load_rag_v02_cases
from verbaops.evaluation.rag_v02_scorer_impl import (
    AssertionStatus,
    FactAssertionAssessment,
)
from verbaops.evaluation.rag_v02_scorer_v2 import audit_scorer_v2

ROOT = Path(__file__).parents[2]


def test_p4_scoring_rejects_incomplete_dev_execution() -> None:
    cases, _case, _fixture, records, _record = _case_fixture_and_records()

    with pytest.raises(ValueError, match="96 complete DEV"):
        score_p4_grounded_records((cases[0],), (records[0],), 0.2554669, repo_root=ROOT)


def _case_fixture_and_records(
    answer: str | None = None,
) -> tuple[list[Any], Any, dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    cases = [
        item
        for item in load_rag_v02_cases(ROOT / "evals/rag/v0.2/questions.jsonl")
        if item.split == "dev"
    ]
    case = next(item for item in cases if item.case_id == "m5d-v02-shipping-001")
    fact = case.expected_facts[0]
    audit = audit_scorer_v2(ROOT)
    fixture = next(
        item
        for item in audit["fixtures"]["facts"]
        if item["case_id"] == case.case_id and item["fact_id"] == fact.fact_id
    )
    records: list[dict[str, Any]] = []
    for current in cases:
        locators = [
            f"{item.document_slug}|{item.document_version}|{item.section}|{item.chunk_index}"
            for item in current.relevance_judgments
            if item.relevance_grade > 0
        ]
        current_answer = (
            answer + " [1]"
            if current.case_id == case.case_id and answer is not None
            else fixture["positive_paraphrases"][0] + " [1]"
            if current.case_id == case.case_id
            else ". ".join(
                f"I cannot verify whether {fact.statement}" for fact in current.expected_facts
            )
            if current.answerable
            else "I'm unable to verify that information from the available company knowledge."
        )
        active = bool(current.answerable and locators)
        diagnostics: dict[str, Any] = {
            "p4_extractive_mode_active": active,
            "p4_extractive_mode_reason": (
                "selected_evidence_no_tool_path" if active else "no_selected_knowledge_evidence"
            ),
            "tool_path_entered": False,
            "p4_extractive_mode_deactivated_after_tool": False,
        }
        if active:
            diagnostics.update(
                {
                    "raw_structured_response": '{"claims":[]}',
                    "parse_success": True,
                    "parse_failure_reason": None,
                    "proposed_claims": [],
                    "claim_validation": [],
                    "accepted_claims": [],
                    "rendered_claims": "",
                    "final_rendered_answer": current_answer,
                    "fallback_used": True,
                    "fallback_reason": "all_claims_rejected",
                }
            )
        records.append(
            {
                "case_id": current.case_id,
                "final_answer": current_answer,
                "public_citations": locators,
                "selected_evidence": locators,
                "top_confidence_score": 0.5 if current.answerable else 0.0,
                "answer_latency_ms": 100.0,
                "cost_usd": 0.001,
                "tool_call_count": 0,
                "p4_diagnostics": diagnostics,
            }
        )
    target_record = next(item for item in records if item["case_id"] == case.case_id)
    return cases, case, fixture, records, target_record


def test_p4_uses_fact_paraphrase_without_changing_historical_scorer() -> None:
    cases, case, fixture, records, record = _case_fixture_and_records()

    p4_report = score_p4_grounded_records(cases, records, 0.2554669, repo_root=ROOT)
    historical_report = score_grounded_records((case,), (record,), 0.2554669)

    assert fixture["positive_paraphrases"][0] in record["final_answer"]
    assert p4_report["expected_fact_coverage"] == {
        "numerator": 1,
        "denominator": 72,
        "value": 1 / 72,
    }
    assert p4_report["groundedness"] == {"numerator": 1, "denominator": 1, "value": 1.0}
    assert p4_report["unsupported_claim_rate"] == 0.0
    assert historical_report["expected_fact_coverage"]["numerator"] == 0
    assert historical_report["groundedness"]["denominator"] == 0


def test_p4_reuses_one_fact_assessment_for_coverage_and_groundedness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases, case, fixture, records, record = _case_fixture_and_records()
    observed_calls: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []

    def classify(
        answer: str,
        aliases: list[str],
        *,
        positive_paraphrases: list[str],
    ) -> FactAssertionAssessment:
        observed_calls.append((answer, tuple(aliases), tuple(positive_paraphrases)))
        if answer == record["final_answer"]:
            return FactAssertionAssessment(AssertionStatus.ASSERTED, True, "authored paraphrase")
        return FactAssertionAssessment(AssertionStatus.REFUSAL, False)

    monkeypatch.setattr(rag_grounding, "classify_labeled_fact_assertion", classify)

    report = score_p4_grounded_records(cases, records, 0.2554669, repo_root=ROOT)

    assert len(observed_calls) == 72
    assert (
        observed_calls.count(
            (
                record["final_answer"],
                case.expected_facts[0].aliases,
                tuple(fixture["positive_paraphrases"]),
            )
        )
        == 1
    )
    assert report["expected_fact_coverage"]["numerator"] == report["groundedness"]["denominator"]
    assert report["groundedness"]["numerator"] == 1
    assert report["unsupported_claim_rate"] == 0.0


@pytest.mark.parametrize(
    "answer",
    [
        "I cannot verify whether standard delivery usually takes three to five business days from dispatch.",
        "Maybe standard delivery usually takes three to five business days from dispatch.",
        'The source says "standard delivery usually takes three to five business days from dispatch."',
    ],
)
def test_p4_scorer_v2_does_not_count_nonassertions(answer: str) -> None:
    cases, _case, _fixture, records, _record = _case_fixture_and_records(answer)
    report = score_p4_grounded_records(cases, records, 0.2554669, repo_root=ROOT)

    assert report["expected_fact_coverage"]["numerator"] == 0
    assert report["groundedness"]["denominator"] == 0
    assert report["scorer_v2_nonrecognition_count"] == 72


def test_p4_fixture_must_match_exact_case_fact_and_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases, case, _fixture, records, _record = _case_fixture_and_records()
    audited = audit_scorer_v2(ROOT)
    tampered = dict(audited)
    tampered["fixtures"] = dict(audited["fixtures"])
    tampered["fixtures"]["facts"] = [dict(item) for item in audited["fixtures"]["facts"]]
    target = next(item for item in tampered["fixtures"]["facts"] if item["case_id"] == case.case_id)
    target["benchmark_aliases"] = ["wrong fact alias"]
    monkeypatch.setattr(rag_grounding, "audit_scorer_v2", lambda _root: tampered)

    with pytest.raises(ValueError, match=r"fixture.*benchmark fact"):
        score_p4_grounded_records(cases, records, 0.2554669, repo_root=ROOT)


def test_p4_report_exposes_trace_diagnostics_and_handle_trust_invariant() -> None:
    cases, _case, _fixture, records, record = _case_fixture_and_records()
    diagnostics = record["p4_diagnostics"]
    diagnostics["proposed_claims"] = [
        {"claim_text": "x", "evidence_handle": "K9", "supporting_excerpt": "x"}
    ]
    diagnostics["claim_validation"] = [
        {
            "index": 0,
            "claim_text": "x",
            "evidence_handle": "K9",
            "supporting_excerpt": "x",
            "handle_valid": False,
            "excerpt_nonempty": True,
            "excerpt_matches_source": None,
            "claim_nonempty": True,
            "claim_matches_excerpt": True,
            "accepted": False,
            "rejection_reason": "invalid_handle",
        }
    ]
    report = score_p4_grounded_records(cases, records, 0.2554669, repo_root=ROOT)

    assert report["p4_diagnostics"]["extractive_mode_case_count"] == 72
    assert report["p4_diagnostics"]["proposed_claim_count"] == 1
    assert report["p4_diagnostics"]["invalid_handle_rejection_count"] == 1
    assert report["p4_diagnostics"]["fabricated_or_non_supplied_evidence_handle_count"] == 1
    assert report["p4_diagnostics"]["zero_fabricated_or_non_supplied_evidence_handles"] is False
