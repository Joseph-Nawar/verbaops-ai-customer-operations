from __future__ import annotations

import json
from dataclasses import replace

import pytest

from tests.agent.test_retrieval_graph import evidence
from verbaops.agent.p4_grounding import (
    finalize_p4_response,
    parse_p4_response,
    render_p4_claims,
    validate_p4_claims,
)
from verbaops.agent.p4_models import P4Claim, P4Response
from verbaops.retrieval.grounding import SAFE_GROUNDING_FALLBACK, CitationFinalizer
from verbaops.retrieval.models import RetrievalEvidence


def _evidence(content: str = "prefix Alpha. Beta. suffix") -> RetrievalEvidence:
    return replace(evidence(), content=content)


def _claim(
    claim_text: str,
    evidence_handle: str = "K1",
    supporting_excerpt: str = "prefix Alpha. Beta. suffix",
) -> P4Claim:
    return P4Claim(
        claim_text=claim_text,
        evidence_handle=evidence_handle,
        supporting_excerpt=supporting_excerpt,
    )


@pytest.mark.parametrize(
    ("content", "parse_success", "reason"),
    [
        ('{"claims":[]}', True, None),
        ("not JSON", False, "invalid_json"),
        ('{"claims":[{"claim_text":"x"}]}', False, "invalid_p4_schema"),
        (None, False, "missing_or_blank_terminal_content"),
        ("  \n", False, "missing_or_blank_terminal_content"),
    ],
)
def test_p4_terminal_parser_classifies_frozen_response_states(
    content: str | None, parse_success: bool, reason: str | None
) -> None:
    result = parse_p4_response(content)

    assert result.parse_success is parse_success
    assert result.parse_failure_reason == reason


@pytest.mark.parametrize(
    "payload",
    [
        {"claim_text": "Alpha.", "evidence_handle": "K1", "supporting_excerpt": ""},
        {"claim_text": "", "evidence_handle": "K1", "supporting_excerpt": "Alpha."},
    ],
)
def test_blank_claim_or_excerpt_fails_schema_validation(payload: dict[str, str]) -> None:
    result = parse_p4_response(json.dumps({"claims": [payload]}))

    assert result.parse_success is False
    assert result.parse_failure_reason == "invalid_p4_schema"


def test_p4_claim_validation_requires_supplied_handle_and_exact_source_excerpt() -> None:
    claims = P4Response(
        claims=[
            _claim("Alpha.", "K9"),
            _claim("Alpha.", "K1", "not present in source"),
            _claim("alpha."),
        ]
    )

    accepted, diagnostics = validate_p4_claims(claims, [_evidence()])

    assert accepted == ()
    assert [item.rejection_reason for item in diagnostics] == [
        "invalid_handle",
        "excerpt_mismatch",
        "claim_not_substring",
    ]
    assert diagnostics[0].handle_valid is False
    assert diagnostics[1].excerpt_matches_source is False
    assert diagnostics[2].claim_matches_excerpt is False


def test_p4_parser_and_finalizer_fail_closed_without_another_generation() -> None:
    result = finalize_p4_response("{broken", [_evidence()], CitationFinalizer())

    assert result.final_response == SAFE_GROUNDING_FALLBACK
    assert result.citations == ()
    assert result.parse_success is False
    assert result.parse_failure_reason == "invalid_json"
    assert result.accepted_claims == ()
    assert result.fallback_reason == "invalid_json"


@pytest.mark.parametrize(
    ("claims", "expected"),
    [
        ([_claim("Alpha.")], "Alpha. [[K1]]"),
        ([_claim("Alpha."), _claim("Beta.")], "Alpha. [[K1]]\nBeta. [[K1]]"),
        ([_claim("Alpha."), _claim("Alpha.")], "Alpha. [[K1]]\nAlpha. [[K1]]"),
    ],
)
def test_p4_renderer_preserves_order_duplicates_and_exact_separators(
    claims: list[P4Claim], expected: str
) -> None:
    accepted, diagnostics = validate_p4_claims(P4Response(claims=claims), [_evidence()])

    assert len(diagnostics) == len(claims)
    assert render_p4_claims(accepted) == expected


def test_p4_partial_rejection_keeps_surviving_claim_order_and_citations() -> None:
    content = json.dumps(
        {
            "claims": [
                _claim("Alpha.").model_dump(),
                _claim("bad", "K9").model_dump(),
                _claim("Beta.").model_dump(),
            ]
        }
    )

    result = finalize_p4_response(content, [_evidence()], CitationFinalizer())

    assert result.rendered_claims == "Alpha. [[K1]]\nBeta. [[K1]]"
    assert result.final_response == "Alpha. [1]\nBeta. [1]"
    assert len(result.citations) == 1
    assert [item.accepted for item in result.claim_diagnostics] == [True, False, True]


def test_all_rejected_p4_claims_use_exact_safe_fallback() -> None:
    content = json.dumps({"claims": [_claim("Alpha.", "K9").model_dump()]})

    result = finalize_p4_response(content, [_evidence()], CitationFinalizer())

    assert result.final_response == SAFE_GROUNDING_FALLBACK
    assert result.citations == ()
    assert result.fallback_reason == "all_claims_rejected"


def test_repeated_handle_uses_existing_citation_finalizer_deduplication() -> None:
    content = json.dumps({"claims": [_claim("Alpha.").model_dump(), _claim("Beta.").model_dump()]})

    result = finalize_p4_response(content, [_evidence()], CitationFinalizer())

    assert result.final_response == "Alpha. [1]\nBeta. [1]"
    assert len(result.citations) == 1
