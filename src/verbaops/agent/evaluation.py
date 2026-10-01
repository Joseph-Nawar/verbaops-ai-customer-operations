"""Explicit, evaluation-only agent candidate configuration."""

from dataclasses import dataclass
from enum import StrEnum

from verbaops.retrieval.evidence_gate import EvidenceGate


class GroundingCandidate(StrEnum):
    P0_CURRENT = "P0_CURRENT"
    P1_PROMPT_V3 = "P1_PROMPT_V3"
    P2_FAIL_CLOSED_CITATIONS = "P2_FAIL_CLOSED_CITATIONS"
    P3_ONE_REPAIR_THEN_FAIL_CLOSED = "P3_ONE_REPAIR_THEN_FAIL_CLOSED"


@dataclass(frozen=True, slots=True)
class AgentEvaluationProfile:
    """Candidate settings passed only by an explicitly constructed evaluation app."""

    grounding_candidate: GroundingCandidate = GroundingCandidate.P0_CURRENT
    evidence_gate: EvidenceGate | None = None
    evidence_gate_threshold: float | None = None
    model_candidate: str = "M0_CURRENT_STAGE5"

    def __post_init__(self) -> None:
        if (self.evidence_gate is None) != (self.evidence_gate_threshold is None):
            raise ValueError("evaluation gate and threshold must be configured together")

    @property
    def prompt_version(self) -> str:
        return "v2" if self.grounding_candidate is GroundingCandidate.P0_CURRENT else "v3"

    @property
    def graph_version(self) -> str:
        return "text-agent-m5d-v1"


__all__ = ["AgentEvaluationProfile", "GroundingCandidate"]
