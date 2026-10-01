"""Explicit, evaluation-only agent candidate configuration."""

from dataclasses import dataclass
from enum import StrEnum

from verbaops.retrieval.evidence_gate import EvidenceGate


class GroundingCandidate(StrEnum):
    P0_CURRENT = "P0_CURRENT"
    P1_PROMPT_V3 = "P1_PROMPT_V3"
    P2_FAIL_CLOSED_CITATIONS = "P2_FAIL_CLOSED_CITATIONS"
    P3_ONE_REPAIR_THEN_FAIL_CLOSED = "P3_ONE_REPAIR_THEN_FAIL_CLOSED"
    P4_EVIDENCE_LINKED_SINGLE_PASS = "P4_EVIDENCE_LINKED_SINGLE_PASS"


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
        if self.grounding_candidate is GroundingCandidate.P0_CURRENT:
            return "v2"
        if self.grounding_candidate is GroundingCandidate.P4_EVIDENCE_LINKED_SINGLE_PASS:
            return "p4-evidence-linked-v1"
        return "v3"

    @property
    def graph_version(self) -> str:
        return "text-agent-m5d-v1"

    @property
    def grounding_finalizer_version(self) -> str | None:
        if self.grounding_candidate is GroundingCandidate.P4_EVIDENCE_LINKED_SINGLE_PASS:
            return "evidence-linked-extractive-single-pass-v1"
        return None


__all__ = ["AgentEvaluationProfile", "GroundingCandidate"]
