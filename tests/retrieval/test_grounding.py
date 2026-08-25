from datetime import date
from uuid import UUID

from verbaops.retrieval.grounding import SAFE_GROUNDING_FALLBACK, CitationFinalizer
from verbaops.retrieval.models import RetrievalEvidence


def evidence(key: str, number: int) -> RetrievalEvidence:
    return RetrievalEvidence(
        evidence_key=key,
        chunk_id=UUID(int=number),
        document_id=UUID(int=number + 10),
        version_id=UUID(int=number + 20),
        document_title=f"Policy {number}",
        document_slug=f"policy-{number}",
        document_version="2026.1",
        section="Return Window",
        effective_date=date(2026, 1, 1),
        content="Return window is 30 days.",
    )


def test_grounding_accepts_only_supplied_handles_deduplicates_and_numbers_by_first_use() -> None:
    result = CitationFinalizer().finalize(
        "Return in 30 days [[K2]]. The same source applies [[K2]] and [[K1]].",
        [evidence("K1", 1), evidence("K2", 2)],
    )

    assert result.content == "Return in 30 days [1]. The same source applies [1] and [2]."
    assert [item.evidence_key for item in result.citations] == ["K2", "K1"]


def test_grounding_uses_safe_fallback_for_fabricated_handles() -> None:
    result = CitationFinalizer().finalize(
        "Issue a refund according to [[K9]].",
        [evidence("K1", 1)],
    )

    assert result.content == SAFE_GROUNDING_FALLBACK
    assert result.citations == ()


def test_grounding_preserves_no_citation_messages() -> None:
    result = CitationFinalizer().finalize("Where is my order?", [evidence("K1", 1)])

    assert result.content == "Where is my order?"
    assert result.citations == ()
