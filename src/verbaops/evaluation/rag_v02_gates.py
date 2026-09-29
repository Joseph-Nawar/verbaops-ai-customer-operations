"""Pure deterministic scoring and selection for rag-v0.2 evidence gates."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from verbaops.evaluation.rag_reports import percentile
from verbaops.retrieval.evidence_gate import EvidenceGate

GATE_COMPLEXITY: dict[EvidenceGate, int] = {
    EvidenceGate.G0_CURRENT_RRF: 1,
    EvidenceGate.G1_DENSE_SIMILARITY: 2,
    EvidenceGate.G2_TOP_EVIDENCE_CROSS_ENCODER: 3,
}
MINIMUM_NO_ANSWER_REJECTION = 0.90
MINIMUM_NO_ANSWER_REJECTED_CASES = 22
ANSWERABLE_ACCEPTANCE_TIE_BAND = 0.02


@dataclass(frozen=True, slots=True)
class GateObservation:
    """One v0.2 DEV case's candidate confidence and measured latency components."""

    case_id: str
    answerable: bool
    confidence: float | None
    latency_components_ms: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class GateThresholdMetrics:
    """Metrics for one observed confidence threshold for one gate candidate."""

    gate: EvidenceGate
    threshold: float
    answerable_accepted: int
    answerable_total: int
    no_answer_rejected: int
    no_answer_total: int
    total_latency_p50_ms: float | None
    total_latency_p95_ms: float | None
    latency_component_p50_ms: Mapping[str, float | None]
    latency_component_p95_ms: Mapping[str, float | None]
    eligible: bool

    @property
    def answerable_acceptance(self) -> float:
        return self.answerable_accepted / self.answerable_total

    @property
    def no_answer_rejection(self) -> float | None:
        if self.no_answer_total == 0:
            return None
        return self.no_answer_rejected / self.no_answer_total

    def as_dict(self) -> dict[str, object]:
        return {
            "gate": self.gate.value,
            "threshold": self.threshold,
            "answerable_accepted": self.answerable_accepted,
            "answerable_total": self.answerable_total,
            "answerable_acceptance": self.answerable_acceptance,
            "no_answer_rejected": self.no_answer_rejected,
            "no_answer_total": self.no_answer_total,
            "no_answer_rejection": self.no_answer_rejection,
            "eligible": self.eligible,
            "total_latency_p50_ms": self.total_latency_p50_ms,
            "total_latency_p95_ms": self.total_latency_p95_ms,
            "latency_component_p50_ms": dict(self.latency_component_p50_ms),
            "latency_component_p95_ms": dict(self.latency_component_p95_ms),
        }


@dataclass(frozen=True, slots=True)
class EvidenceGateCalibration:
    """All finite observed thresholds and the best eligible threshold for one gate."""

    gate: EvidenceGate
    thresholds: tuple[float, ...]
    evaluations: tuple[GateThresholdMetrics, ...]
    selected: GateThresholdMetrics | None

    def as_dict(self) -> dict[str, object]:
        return {
            "gate": self.gate.value,
            "thresholds": list(self.thresholds),
            "selected": self.selected.as_dict() if self.selected is not None else None,
            "evaluations": [item.as_dict() for item in self.evaluations],
        }


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def evidence_accepted(confidence: float | None, threshold: float) -> bool:
    """Apply the preregistered inclusive threshold; invalid confidence fails closed."""

    finite_threshold = _finite_number(threshold)
    finite_confidence = _finite_number(confidence)
    return (
        finite_threshold is not None
        and finite_confidence is not None
        and finite_confidence >= finite_threshold
    )


def _validate_observations(observations: Sequence[GateObservation]) -> None:
    if not observations:
        raise ValueError("evidence-gate calibration requires DEV observations")
    case_ids: set[str] = set()
    if not any(item.answerable for item in observations):
        raise ValueError("evidence-gate calibration requires answerable DEV cases")
    if not any(not item.answerable for item in observations):
        raise ValueError("evidence-gate calibration requires no-answer DEV cases")
    for item in observations:
        if not item.case_id or item.case_id in case_ids:
            raise ValueError("evidence-gate observations require unique non-empty case IDs")
        case_ids.add(item.case_id)
        for name, raw_duration in item.latency_components_ms.items():
            duration = _finite_number(raw_duration)
            if not name or duration is None or duration < 0:
                raise ValueError("gate latency components must be named, finite, and non-negative")


def _latency_metrics(
    observations: Sequence[GateObservation],
) -> tuple[float | None, float | None, dict[str, float | None], dict[str, float | None]]:
    totals: list[float] = []
    components: defaultdict[str, list[float]] = defaultdict(list)
    for observation in observations:
        total = 0.0
        for name, raw_duration in observation.latency_components_ms.items():
            duration = _finite_number(raw_duration)
            if duration is None:
                continue
            components[name].append(duration)
            total += duration
        totals.append(total)
    return (
        percentile(totals, 0.50),
        percentile(totals, 0.95),
        {name: percentile(values, 0.50) for name, values in sorted(components.items())},
        {name: percentile(values, 0.95) for name, values in sorted(components.items())},
    )


def calibrate_evidence_gate(
    gate: EvidenceGate,
    observations: Sequence[GateObservation],
) -> EvidenceGateCalibration:
    """Enumerate finite observed scores and select the best threshold meeting 90%."""

    _validate_observations(observations)
    finite_scores = tuple(
        sorted(
            {
                finite_score
                for item in observations
                if (finite_score := _finite_number(item.confidence)) is not None
            }
        )
    )
    answerable_total = sum(item.answerable for item in observations)
    no_answer_total = len(observations) - answerable_total
    latency_p50, latency_p95, component_p50, component_p95 = _latency_metrics(observations)
    evaluations: list[GateThresholdMetrics] = []
    for threshold in finite_scores:
        answerable_accepted = sum(
            item.answerable and evidence_accepted(item.confidence, threshold)
            for item in observations
        )
        no_answer_rejected = sum(
            not item.answerable and not evidence_accepted(item.confidence, threshold)
            for item in observations
        )
        no_answer_rejection = no_answer_rejected / no_answer_total
        evaluations.append(
            GateThresholdMetrics(
                gate=gate,
                threshold=threshold,
                answerable_accepted=answerable_accepted,
                answerable_total=answerable_total,
                no_answer_rejected=no_answer_rejected,
                no_answer_total=no_answer_total,
                total_latency_p50_ms=latency_p50,
                total_latency_p95_ms=latency_p95,
                latency_component_p50_ms=component_p50,
                latency_component_p95_ms=component_p95,
                eligible=no_answer_rejection >= MINIMUM_NO_ANSWER_REJECTION
                and no_answer_rejected >= MINIMUM_NO_ANSWER_REJECTED_CASES,
            )
        )
    eligible = [item for item in evaluations if item.eligible]
    selected = (
        min(
            eligible,
            key=lambda item: (
                -item.answerable_accepted,
                -item.no_answer_rejected,
                -item.threshold,
            ),
        )
        if eligible
        else None
    )
    return EvidenceGateCalibration(
        gate=gate,
        thresholds=finite_scores,
        evaluations=tuple(evaluations),
        selected=selected,
    )


def select_evidence_gate(
    calibrations: Sequence[EvidenceGateCalibration],
) -> GateThresholdMetrics | None:
    """Choose among eligible gates using the frozen 2-point latency tie band."""

    selected = [
        calibration.selected
        for calibration in calibrations
        if calibration.selected is not None and calibration.selected.eligible
    ]
    if not selected:
        return None
    best_acceptance = max(item.answerable_acceptance for item in selected)
    tied = [
        item
        for item in selected
        if best_acceptance - item.answerable_acceptance <= ANSWERABLE_ACCEPTANCE_TIE_BAND
    ]
    return min(
        tied,
        key=lambda item: (
            item.total_latency_p95_ms if item.total_latency_p95_ms is not None else math.inf,
            GATE_COMPLEXITY[item.gate],
            item.gate.value,
        ),
    )


__all__ = [
    "ANSWERABLE_ACCEPTANCE_TIE_BAND",
    "GATE_COMPLEXITY",
    "EvidenceGate",
    "EvidenceGateCalibration",
    "GateObservation",
    "GateThresholdMetrics",
    "calibrate_evidence_gate",
    "evidence_accepted",
    "select_evidence_gate",
]
