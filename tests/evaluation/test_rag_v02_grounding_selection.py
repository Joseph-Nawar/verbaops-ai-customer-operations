from __future__ import annotations

from typing import Any

from verbaops.evaluation.rag_v02_grounding_selection import (
    meets_m5d_grounding_quality_gate,
    select_grounding_candidate,
)


def _report(
    *,
    citation: float = 0.96,
    citation_denominator: int = 50,
    groundedness: float = 0.91,
    unsupported: float = 0.09,
    coverage: float = 0.72,
    p95: float = 100.0,
    cost: float | None = 0.01,
) -> dict[str, Any]:
    return {
        "citation_precision": {
            "numerator": round(citation * citation_denominator),
            "denominator": citation_denominator,
            "value": citation,
        },
        "groundedness": {"numerator": 91, "denominator": 100, "value": groundedness},
        "unsupported_claim_rate": unsupported,
        "expected_fact_coverage": {"numerator": 72, "denominator": 100, "value": coverage},
        "answer_latency_p95_ms": p95,
        "mean_cost_usd_over_costed_observations": cost,
    }


def test_quality_gate_requires_citation_denominator_and_all_four_floors() -> None:
    assert meets_m5d_grounding_quality_gate(_report())
    assert not meets_m5d_grounding_quality_gate(_report(citation_denominator=0))
    assert not meets_m5d_grounding_quality_gate(_report(citation=0.94))
    assert not meets_m5d_grounding_quality_gate(_report(groundedness=0.89))
    assert not meets_m5d_grounding_quality_gate(_report(unsupported=0.11))
    assert not meets_m5d_grounding_quality_gate(_report(coverage=0.69))


def test_candidate_tie_hierarchy_applies_latency_then_cost_then_simplicity() -> None:
    reports = {
        "P0_CURRENT": _report(p95=120.0, cost=0.01),
        "P1_PROMPT_V3": _report(p95=100.0, cost=0.02),
        "P2_FAIL_CLOSED_CITATIONS": _report(p95=100.0, cost=0.01),
        "P3_ONE_REPAIR_THEN_FAIL_CLOSED": _report(p95=100.0, cost=0.01),
    }

    assert select_grounding_candidate(reports) == "P2_FAIL_CLOSED_CITATIONS"


def test_no_grounding_candidate_is_selected_when_quality_floors_fail() -> None:
    assert select_grounding_candidate({"P1_PROMPT_V3": _report(unsupported=0.2)}) is None
