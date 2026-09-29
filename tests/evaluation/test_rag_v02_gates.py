"""Pure, provider-free contracts for M5D evidence-gate calibration."""

from __future__ import annotations

from verbaops.evaluation.rag_v02_gates import (
    EvidenceGate,
    GateObservation,
    calibrate_evidence_gate,
    select_evidence_gate,
)


def _observations(
    gate: EvidenceGate,
    *,
    accepted_answerable: int = 72,
    rejected_no_answer: int = 24,
    latency_components_ms: dict[str, float] | None = None,
) -> list[GateObservation]:
    components = latency_components_ms or {"hybrid_retrieval": 10.0}
    answerable = [
        GateObservation(
            case_id=f"answerable-{index}",
            answerable=True,
            confidence=1.0 if index < accepted_answerable else 0.0,
            latency_components_ms=components,
        )
        for index in range(72)
    ]
    no_answer = [
        GateObservation(
            case_id=f"no-answer-{index}",
            answerable=False,
            confidence=0.0 if index < rejected_no_answer else 1.0,
            latency_components_ms=components,
        )
        for index in range(24)
    ]
    return answerable + no_answer


def test_gate_thresholds_are_inclusive_and_choose_the_best_eligible_observed_score() -> None:
    observations = _observations(
        EvidenceGate.G0_CURRENT_RRF,
        rejected_no_answer=22,
    )

    calibration = calibrate_evidence_gate(EvidenceGate.G0_CURRENT_RRF, observations)

    assert calibration.thresholds == (0.0, 1.0)
    assert calibration.selected is not None
    assert calibration.selected.threshold == 1.0
    assert calibration.selected.answerable_accepted == 72
    assert calibration.selected.answerable_total == 72
    assert calibration.selected.no_answer_rejected == 22
    assert calibration.selected.no_answer_total == 24
    assert calibration.selected.no_answer_rejection == 22 / 24
    assert calibration.selected.eligible is True


def test_missing_and_non_finite_gate_scores_fail_closed() -> None:
    observations = _observations(EvidenceGate.G1_DENSE_SIMILARITY)
    observations[0] = GateObservation(
        case_id="answerable-0",
        answerable=True,
        confidence=None,
        latency_components_ms={"hybrid_retrieval": 10.0, "e5_vector_fetch": 2.0},
    )
    observations[1] = GateObservation(
        case_id="answerable-1",
        answerable=True,
        confidence=float("nan"),
        latency_components_ms={"hybrid_retrieval": 10.0, "e5_vector_fetch": 2.0},
    )
    observations[72] = GateObservation(
        case_id="no-answer-0",
        answerable=False,
        confidence=None,
        latency_components_ms={"hybrid_retrieval": 10.0, "e5_vector_fetch": 2.0},
    )
    observations[73] = GateObservation(
        case_id="no-answer-1",
        answerable=False,
        confidence=float("inf"),
        latency_components_ms={"hybrid_retrieval": 10.0, "e5_vector_fetch": 2.0},
    )

    calibration = calibrate_evidence_gate(EvidenceGate.G1_DENSE_SIMILARITY, observations)

    assert calibration.selected is not None
    assert calibration.selected.answerable_accepted == 70
    assert calibration.selected.no_answer_rejected == 24


def test_gate_latency_sums_candidate_components_before_percentiles() -> None:
    calibration = calibrate_evidence_gate(
        EvidenceGate.G1_DENSE_SIMILARITY,
        _observations(
            EvidenceGate.G1_DENSE_SIMILARITY,
            latency_components_ms={
                "hybrid_retrieval": 10.0,
                "e5_candidate_vector_fetch": 2.0,
                "e5_cosine_scoring": 1.0,
            },
        ),
    )

    assert calibration.selected is not None
    assert calibration.selected.total_latency_p50_ms == 13.0
    assert calibration.selected.total_latency_p95_ms == 13.0
    assert calibration.selected.latency_component_p95_ms == {
        "hybrid_retrieval": 10.0,
        "e5_candidate_vector_fetch": 2.0,
        "e5_cosine_scoring": 1.0,
    }


def test_cross_gate_selection_uses_latency_inside_two_point_acceptance_band() -> None:
    g0 = calibrate_evidence_gate(
        EvidenceGate.G0_CURRENT_RRF,
        _observations(EvidenceGate.G0_CURRENT_RRF, accepted_answerable=72, rejected_no_answer=22),
    )
    g1 = calibrate_evidence_gate(
        EvidenceGate.G1_DENSE_SIMILARITY,
        _observations(
            EvidenceGate.G1_DENSE_SIMILARITY,
            accepted_answerable=71,
            rejected_no_answer=24,
            latency_components_ms={"hybrid_retrieval": 5.0, "e5_score": 1.0},
        ),
    )

    selected = select_evidence_gate([g0, g1])

    assert selected is not None
    assert selected.gate is EvidenceGate.G1_DENSE_SIMILARITY
    assert selected.answerable_acceptance == 71 / 72
    assert selected.total_latency_p95_ms == 6.0


def test_cross_gate_selection_prefers_simpler_candidate_when_acceptance_and_latency_tie() -> None:
    g0 = calibrate_evidence_gate(
        EvidenceGate.G0_CURRENT_RRF,
        _observations(EvidenceGate.G0_CURRENT_RRF, accepted_answerable=70, rejected_no_answer=24),
    )
    g1 = calibrate_evidence_gate(
        EvidenceGate.G1_DENSE_SIMILARITY,
        _observations(
            EvidenceGate.G1_DENSE_SIMILARITY,
            accepted_answerable=70,
            rejected_no_answer=24,
            latency_components_ms={"hybrid_retrieval": 9.0, "e5_score": 1.0},
        ),
    )

    selected = select_evidence_gate([g1, g0])

    assert selected is not None
    assert selected.gate is EvidenceGate.G0_CURRENT_RRF


def test_no_gate_is_selected_when_none_meets_the_no_answer_guard() -> None:
    calibration = calibrate_evidence_gate(
        EvidenceGate.G2_TOP_EVIDENCE_CROSS_ENCODER,
        _observations(
            EvidenceGate.G2_TOP_EVIDENCE_CROSS_ENCODER,
            rejected_no_answer=21,
            latency_components_ms={"hybrid_retrieval": 10.0, "cross_encoder": 4.0},
        ),
    )

    assert calibration.selected is None
    assert select_evidence_gate([calibration]) is None
