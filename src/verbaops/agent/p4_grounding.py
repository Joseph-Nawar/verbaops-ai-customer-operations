"""Pure parsing and extractive validation for the evaluation-only P4 candidate."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from verbaops.agent.p4_models import P4Claim, P4Response
from verbaops.retrieval.grounding import SAFE_GROUNDING_FALLBACK, CitationFinalizer
from verbaops.retrieval.models import RetrievalEvidence


@dataclass(frozen=True, slots=True)
class P4ParseResult:
    raw_structured_response: str | None
    response: P4Response | None
    parse_success: bool
    parse_failure_reason: str | None


@dataclass(frozen=True, slots=True)
class P4ClaimValidation:
    index: int
    claim_text: str
    evidence_handle: str
    supporting_excerpt: str
    handle_valid: bool
    excerpt_nonempty: bool
    excerpt_matches_source: bool | None
    claim_nonempty: bool
    claim_matches_excerpt: bool | None
    accepted: bool
    rejection_reason: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "claim_text": self.claim_text,
            "evidence_handle": self.evidence_handle,
            "supporting_excerpt": self.supporting_excerpt,
            "handle_valid": self.handle_valid,
            "excerpt_nonempty": self.excerpt_nonempty,
            "excerpt_matches_source": self.excerpt_matches_source,
            "claim_nonempty": self.claim_nonempty,
            "claim_matches_excerpt": self.claim_matches_excerpt,
            "accepted": self.accepted,
            "rejection_reason": self.rejection_reason,
        }


@dataclass(frozen=True, slots=True)
class P4FinalizationResult:
    final_response: str
    citations: tuple[RetrievalEvidence, ...]
    raw_structured_response: str | None
    parse_success: bool
    parse_failure_reason: str | None
    proposed_claims: tuple[P4Claim, ...]
    accepted_claims: tuple[P4Claim, ...]
    claim_diagnostics: tuple[P4ClaimValidation, ...]
    rendered_claims: str
    fallback_reason: str | None

    def diagnostics(self) -> dict[str, Any]:
        """Return only P4 response and validation details for the run sidecar."""

        return {
            "raw_structured_response": self.raw_structured_response,
            "parse_success": self.parse_success,
            "parse_failure_reason": self.parse_failure_reason,
            "proposed_claims": [claim.model_dump(mode="json") for claim in self.proposed_claims],
            "claim_validation": [item.as_dict() for item in self.claim_diagnostics],
            "accepted_claims": [claim.model_dump(mode="json") for claim in self.accepted_claims],
            "rendered_claims": self.rendered_claims,
            "final_rendered_answer": self.final_response,
            "fallback_used": self.fallback_reason is not None,
            "fallback_reason": self.fallback_reason,
        }


def parse_p4_response(content: str | None) -> P4ParseResult:
    """Parse one terminal P4 response and classify malformed output safely."""

    if content is None or not content.strip():
        return P4ParseResult(content, None, False, "missing_or_blank_terminal_content")
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return P4ParseResult(content, None, False, "invalid_json")
    try:
        response = P4Response.model_validate(payload)
    except ValidationError:
        return P4ParseResult(content, None, False, "invalid_p4_schema")
    return P4ParseResult(content, response, True, None)


def validate_p4_claims(
    response: P4Response,
    evidence: list[RetrievalEvidence],
) -> tuple[tuple[P4Claim, ...], tuple[P4ClaimValidation, ...]]:
    """Keep only claims with a supplied handle and exact nested source substrings."""

    by_handle = {item.evidence_key: item for item in evidence}
    accepted: list[P4Claim] = []
    diagnostics: list[P4ClaimValidation] = []
    for index, claim in enumerate(response.claims):
        source = by_handle.get(claim.evidence_handle)
        handle_valid = source is not None
        excerpt_nonempty = bool(claim.supporting_excerpt.strip())
        excerpt_matches_source = (
            claim.supporting_excerpt in source.content if source is not None else None
        )
        claim_nonempty = bool(claim.claim_text.strip())
        claim_matches_excerpt = (
            claim.claim_text in claim.supporting_excerpt
            if excerpt_nonempty and claim_nonempty
            else False
        )

        rejection_reason: str | None = None
        if not handle_valid:
            rejection_reason = "invalid_handle"
        elif not excerpt_nonempty:
            rejection_reason = "empty_excerpt"
        elif excerpt_matches_source is not True:
            rejection_reason = "excerpt_mismatch"
        elif not claim_nonempty:
            rejection_reason = "empty_claim"
        elif not claim_matches_excerpt:
            rejection_reason = "claim_not_substring"

        is_accepted = rejection_reason is None
        if is_accepted:
            accepted.append(claim)
        diagnostics.append(
            P4ClaimValidation(
                index=index,
                claim_text=claim.claim_text,
                evidence_handle=claim.evidence_handle,
                supporting_excerpt=claim.supporting_excerpt,
                handle_valid=handle_valid,
                excerpt_nonempty=excerpt_nonempty,
                excerpt_matches_source=excerpt_matches_source,
                claim_nonempty=claim_nonempty,
                claim_matches_excerpt=claim_matches_excerpt,
                accepted=is_accepted,
                rejection_reason=rejection_reason,
            )
        )
    return tuple(accepted), tuple(diagnostics)


def render_p4_claims(claims: tuple[P4Claim, ...]) -> str:
    """Render validated claims with only their server-issued evidence handles."""

    return "\n".join(f"{claim.claim_text} [[{claim.evidence_handle}]]" for claim in claims)


def finalize_p4_response(
    content: str | None,
    evidence: list[RetrievalEvidence],
    citation_finalizer: CitationFinalizer,
) -> P4FinalizationResult:
    """Parse, validate, render, and pass P4 claims through the shared finalizer."""

    parsed = parse_p4_response(content)
    if parsed.response is None:
        return P4FinalizationResult(
            final_response=SAFE_GROUNDING_FALLBACK,
            citations=(),
            raw_structured_response=parsed.raw_structured_response,
            parse_success=False,
            parse_failure_reason=parsed.parse_failure_reason,
            proposed_claims=(),
            accepted_claims=(),
            claim_diagnostics=(),
            rendered_claims="",
            fallback_reason=parsed.parse_failure_reason,
        )

    accepted, diagnostics = validate_p4_claims(parsed.response, evidence)
    rendered_claims = render_p4_claims(accepted)
    if not accepted:
        fallback_reason = "all_claims_rejected"
        return P4FinalizationResult(
            final_response=SAFE_GROUNDING_FALLBACK,
            citations=(),
            raw_structured_response=content,
            parse_success=True,
            parse_failure_reason=None,
            proposed_claims=tuple(parsed.response.claims),
            accepted_claims=(),
            claim_diagnostics=diagnostics,
            rendered_claims=rendered_claims,
            fallback_reason=fallback_reason,
        )

    grounded = citation_finalizer.finalize(rendered_claims, evidence)
    if not grounded.citations:
        return P4FinalizationResult(
            final_response=SAFE_GROUNDING_FALLBACK,
            citations=(),
            raw_structured_response=content,
            parse_success=True,
            parse_failure_reason=None,
            proposed_claims=tuple(parsed.response.claims),
            accepted_claims=accepted,
            claim_diagnostics=diagnostics,
            rendered_claims=rendered_claims,
            fallback_reason="citation_finalizer_rejected_claims",
        )
    return P4FinalizationResult(
        final_response=grounded.content,
        citations=grounded.citations,
        raw_structured_response=content,
        parse_success=True,
        parse_failure_reason=None,
        proposed_claims=tuple(parsed.response.claims),
        accepted_claims=accepted,
        claim_diagnostics=diagnostics,
        rendered_claims=rendered_claims,
        fallback_reason=None,
    )


__all__ = [
    "P4ClaimValidation",
    "P4FinalizationResult",
    "P4ParseResult",
    "finalize_p4_response",
    "parse_p4_response",
    "render_p4_claims",
    "validate_p4_claims",
]
