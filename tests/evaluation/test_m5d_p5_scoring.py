from __future__ import annotations

from typing import Any

import pytest

import verbaops.evaluation.rag_grounding as rag_grounding
from tests.evaluation.test_m5d_p4_scoring import ROOT
from verbaops.agent.p4_grounding import empty_p4_response_diagnostics, finalize_p4_response
from verbaops.evaluation.p5_trace import project_p5_diagnostics
from verbaops.evaluation.rag_grounding import score_grounded_records, score_p5_grounded_records
from verbaops.evaluation.rag_v02 import load_rag_v02_cases
from verbaops.evaluation.rag_v02_scorer_impl import AssertionStatus, FactAssertionAssessment
from verbaops.evaluation.rag_v02_scorer_v2 import audit_scorer_v2
from verbaops.retrieval.grounding import CitationFinalizer


def _cases_and_records() -> tuple[list[Any], list[dict[str, Any]], dict[str, Any]]:
    cases = [
        item
        for item in load_rag_v02_cases(ROOT / "evals/rag/v0.2/questions.jsonl")
        if item.split == "dev"
    ]
    audit = audit_scorer_v2(ROOT)
    fixture = next(
        item for item in audit["fixtures"]["facts"] if item["case_id"] == "m5d-v02-shipping-001"
    )
    empty = empty_p4_response_diagnostics()
    parsed = finalize_p4_response('{"claims":[]}', [], CitationFinalizer()).diagnostics()
    records = []
    for case in cases:
        locators = [
            f"{item.document_slug}|{item.document_version}|{item.section}|{item.chunk_index}"
            for item in case.relevance_judgments
            if item.relevance_grade > 0
        ]
        answer = (
            f"{fixture['positive_paraphrases'][0]} [1]"
            if case.case_id == "m5d-v02-shipping-001"
            else ". ".join(
                f"I cannot verify whether {fact.statement}" for fact in case.expected_facts
            )
            if case.answerable
            else "I'm unable to verify that information from the available company knowledge."
        )
        p4_diagnostics = parsed if case.answerable else empty
        p5_diagnostics = project_p5_diagnostics(
            p4_diagnostics,
            knowledge_mode_active=bool(case.answerable),
            tool_path_entered=False,
        )
        records.append(
            {
                "case_id": case.case_id,
                "final_answer": answer,
                "public_citations": locators,
                "selected_evidence": locators,
                "top_confidence_score": 0.5 if case.answerable else 0.0,
                "answer_latency_ms": 100.0,
                "cost_usd": 0.001,
                "tool_call_count": 0,
                "p5_diagnostics": p5_diagnostics,
            }
        )
    return cases, records, fixture


def test_p5_scoring_uses_exact_fact_fixture_once_for_coverage_and_groundedness() -> None:
    cases, records, fixture = _cases_and_records()
    report = score_p5_grounded_records(cases, records, 0.2554669, repo_root=ROOT)
    target_case = next(case for case in cases if case.case_id == "m5d-v02-shipping-001")
    target = next(record for record in records if record["case_id"] == "m5d-v02-shipping-001")
    historical = score_grounded_records((target_case,), (target,), 0.2554669)

    assert report["expected_fact_coverage"]["numerator"] == 1
    assert report["groundedness"]["denominator"] == 1
    assert report["groundedness"]["numerator"] == 1
    assert report["scorer_v2_nonrecognition_count"] == 71
    assert "p5_diagnostics" in report
    assert "p4_diagnostics" not in report
    assert historical["expected_fact_coverage"]["numerator"] == 0
    assert fixture["positive_paraphrases"][0] in target["final_answer"]


def test_p5_scoring_calls_frozen_scorer_once_per_fact_and_reuses_assessment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases, records, fixture = _cases_and_records()
    target_case = next(case for case in cases if case.case_id == "m5d-v02-shipping-001")
    target_record = next(record for record in records if record["case_id"] == target_case.case_id)
    calls: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []

    def classify(
        answer: str, aliases: list[str], *, positive_paraphrases: list[str]
    ) -> FactAssertionAssessment:
        calls.append((answer, tuple(aliases), tuple(positive_paraphrases)))
        if answer == target_record["final_answer"]:
            return FactAssertionAssessment(AssertionStatus.ASSERTED, True, "authored paraphrase")
        return FactAssertionAssessment(AssertionStatus.REFUSAL, False)

    monkeypatch.setattr(rag_grounding, "classify_labeled_fact_assertion", classify)

    report = score_p5_grounded_records(cases, records, 0.2554669, repo_root=ROOT)

    assert len(calls) == 72
    assert (
        calls.count(
            (
                target_record["final_answer"],
                tuple(target_case.expected_facts[0].aliases),
                tuple(fixture["positive_paraphrases"]),
            )
        )
        == 1
    )
    assert report["expected_fact_coverage"]["numerator"] == report["groundedness"]["denominator"]
    assert report["groundedness"]["numerator"] == 1


def test_p5_report_exposes_trace_diagnostics_and_fabricated_handle_invariant() -> None:
    cases, records, _fixture = _cases_and_records()
    target = next(record for record in records if record["case_id"] == "m5d-v02-shipping-001")
    claim = {"claim_text": "x", "evidence_handle": "K9", "supporting_excerpt": "x"}
    target["p5_diagnostics"].update(
        {
            "proposed_claims": [claim],
            "proposed_evidence_handle_per_claim": ["K9"],
            "proposed_excerpt_per_claim": ["x"],
            "handle_validation_result_per_claim": [False],
            "excerpt_validation_result_per_claim": [None],
            "deterministic_rejection_reason_per_claim": ["invalid_handle"],
            "rendered_final_claims": "",
            "fallback_used": True,
            "fallback_reason": "all_claims_rejected",
        }
    )

    report = score_p5_grounded_records(cases, records, 0.2554669, repo_root=ROOT)

    assert report["p5_diagnostics"]["extractive_mode_case_count"] == 72
    assert report["p5_diagnostics"]["proposed_claim_count"] == 1
    assert report["p5_diagnostics"]["accepted_claim_count"] == 0
    assert report["p5_diagnostics"]["fabricated_or_non_supplied_evidence_handle_count"] == 1
    assert report["p5_diagnostics"]["zero_fabricated_or_non_supplied_evidence_handles"] is False


def test_p5_scoring_rejects_incomplete_records_before_scoring() -> None:
    cases, records, _fixture = _cases_and_records()

    with pytest.raises(ValueError, match="96 complete DEV"):
        score_p5_grounded_records(cases[:1], records[:1], 0.2554669, repo_root=ROOT)
