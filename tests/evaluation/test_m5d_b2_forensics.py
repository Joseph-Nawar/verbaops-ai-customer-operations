from pathlib import Path

from verbaops.evaluation.m5d_b2_forensics import (
    build_case_taxonomy,
    build_extended_analysis,
    summarize_taxonomy,
)

ROOT = Path(__file__).resolve().parents[2]


def test_case_taxonomy_uses_all_answerable_dev_facts_and_frozen_gate() -> None:
    rows = build_case_taxonomy(ROOT)
    summary = summarize_taxonomy(rows)

    assert len(rows) == 72
    assert summary["retrieval_and_gate"] == {
        "support_absent_from_final_five": 3,
        "support_present_in_final_five": 69,
        "g2_accepted": 56,
        "support_present_and_g2_accepted": 56,
    }
    assert summary["candidates"]["P0_CURRENT"]["expected_fact_recognized"] == 4
    assert summary["candidates"]["P2_FAIL_CLOSED_CITATIONS"]["expected_fact_recognized"] == 0
    assert summary["candidates"]["P3_ONE_REPAIR_THEN_FAIL_CLOSED"]["expected_fact_recognized"] == 1
    assert (
        summary["candidates"]["P2_FAIL_CLOSED_CITATIONS"]["expected_support_locator_cited_cases"]
        == 48
    )
    assert (
        summary["candidates"]["P3_ONE_REPAIR_THEN_FAIL_CLOSED"][
            "expected_support_locator_cited_cases"
        ]
        == 50
    )
    assert (
        summary["candidates"]["P2_FAIL_CLOSED_CITATIONS"][
            "potential_evaluator_recognition_gap_review_flags"
        ]
        == 31
    )
    assert (
        summary["candidates"]["P3_ONE_REPAIR_THEN_FAIL_CLOSED"][
            "potential_evaluator_recognition_gap_review_flags"
        ]
        == 27
    )
    assert all(row["g2_confidence"] is not None for row in rows)
    assert all(
        not fact["candidate_outcomes"]["P2_FAIL_CLOSED_CITATIONS"]["raw_model_answer_available"]
        for row in rows
        for fact in row["expected_facts"]
    )


def test_accepted_nonrecognition_is_not_labeled_as_fact_omission() -> None:
    rows = build_case_taxonomy(ROOT)
    summary = summarize_taxonomy(rows)

    expected_nonrecognition = {
        "P0_CURRENT": 52,
        "P2_FAIL_CLOSED_CITATIONS": 56,
        "P3_ONE_REPAIR_THEN_FAIL_CLOSED": 55,
    }
    for candidate, count in expected_nonrecognition.items():
        aggregate = summary["candidates"][candidate]
        assert aggregate["accepted_not_recognized_by_frozen_evaluator"] == count
        assert not any("omitted" in key or "omission" in key for key in aggregate)


def test_committed_citation_counts_match_frozen_candidate_reports() -> None:
    rows = build_case_taxonomy(ROOT)
    summary = summarize_taxonomy(rows)

    assert summary["candidates"]["P0_CURRENT"]["citation_precision_answerable_only"] == {
        "numerator": 12,
        "denominator": 18,
        "value": 12 / 18,
    }
    assert summary["candidates"]["P2_FAIL_CLOSED_CITATIONS"][
        "citation_precision_answerable_only"
    ] == {
        "numerator": 48,
        "denominator": 70,
        "value": 48 / 70,
    }
    assert summary["candidates"]["P3_ONE_REPAIR_THEN_FAIL_CLOSED"][
        "citation_precision_answerable_only"
    ] == {
        "numerator": 50,
        "denominator": 76,
        "value": 50 / 76,
    }
    extended = build_extended_analysis(ROOT, rows)
    assert (
        extended["candidate_citation_audit"]["P2_FAIL_CLOSED_CITATIONS"]["all_dev_citations"] == 71
    )
    assert (
        extended["candidate_citation_audit"]["P3_ONE_REPAIR_THEN_FAIL_CLOSED"]["all_dev_citations"]
        == 79
    )
    assert (
        extended["candidate_citation_audit"]["P3_ONE_REPAIR_THEN_FAIL_CLOSED"][
            "citations_outside_supplied_evidence"
        ]
        == 0
    )
    provenance = extended["provenance"]
    assert provenance["application_under_test_sha"] == "7f82c565e7f9fc085f2d81c2c04a9861444837a1"
    assert provenance["evaluation_harness_sha"] == "86c81196e7ed4c967eec62bfc2cab9484820529c"
    assert provenance["release_holdout_executed"] is False
    assert provenance["selection_json_present"] is False
    assert provenance["provider_calls_made"] is False
    assert all(len(item["sha256"]) == 64 for item in provenance["input_artifacts"])


def test_tool_and_repair_deltas_are_descriptive_and_candidate_scoped() -> None:
    rows = build_case_taxonomy(ROOT)
    summary = summarize_taxonomy(rows)
    extended = build_extended_analysis(ROOT, rows)

    assert summary["candidates"]["P0_CURRENT"]["policy_category_tool_cases"] == 0
    assert summary["candidates"]["P2_FAIL_CLOSED_CITATIONS"]["policy_category_tool_case_ids"] == [
        "m5d-v02-shipping-004",
        "m5d-v02-returns-010",
        "m5d-v02-payments-006",
    ]
    assert summary["candidates"]["P3_ONE_REPAIR_THEN_FAIL_CLOSED"][
        "policy_category_tool_case_ids"
    ] == [
        "m5d-v02-shipping-001",
        "m5d-v02-warranty-008",
    ]
    repair = extended["p3_repair_audit"]
    assert (
        repair["attempts_all_dev"],
        repair["successes_all_dev"],
        repair["failures_all_dev"],
    ) == (9, 3, 6)
    assert (
        repair["answerable_case_attempts"],
        repair["answerable_case_successes"],
        repair["answerable_case_failures"],
    ) == (8, 2, 6)
    assert extended["p2_vs_p3_answerable_case_delta"]["answer_same"] == 3
    assert extended["p2_vs_p3_answerable_case_delta"]["recognized_fact_case_ids_p3_only"] == [
        "m5d-v02-shipping-003"
    ]
