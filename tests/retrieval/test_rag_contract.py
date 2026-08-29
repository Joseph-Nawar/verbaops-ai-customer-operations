from datetime import date
from uuid import UUID

import pytest

from verbaops.knowledge.embeddings import deterministic_embedding
from verbaops.knowledge.profiles import format_passage, format_query
from verbaops.retrieval.grounding import CitationFinalizer
from verbaops.retrieval.models import RetrievalEvidence


@pytest.mark.contract
def test_provider_free_rag_contract_has_stable_e5_and_grounding_behavior() -> None:
    query = format_query("  Where   is the return policy? ")
    passage = format_passage("Returns are accepted within thirty days.")

    assert query == "query: Where is the return policy?"
    assert passage == "passage: Returns are accepted within thirty days."
    assert deterministic_embedding(query) == deterministic_embedding(query)
    assert len(deterministic_embedding(passage)) == 768

    evidence = RetrievalEvidence(
        evidence_key="K1",
        chunk_id=UUID(int=1),
        document_id=UUID(int=2),
        version_id=UUID(int=3),
        document_title="Returns",
        document_slug="returns",
        document_version="1.0.0",
        section="Policy",
        effective_date=date(2026, 1, 1),
        content="Returns are accepted within thirty days.",
    )
    finalized = CitationFinalizer().finalize("The policy is [[K1]].", [evidence])
    assert finalized.content == "The policy is [1]."
    assert finalized.citations[0].document_slug == "returns"
