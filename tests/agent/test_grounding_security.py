from typing import Any, cast
from uuid import uuid4

import pytest

from tests.agent.test_retrieval_graph import context, response, state
from tests.support.fake_llm import ScriptedLLMClient
from verbaops.agent.graph import build_agent_graph
from verbaops.retrieval.models import RetrievalResult, RetrievalStatus


class UnavailableRetrieval:
    async def retrieve(self, **_kwargs: Any) -> RetrievalResult:
        return RetrievalResult(
            invocation_id=uuid4(),
            status=RetrievalStatus.UNAVAILABLE,
            evidence=(),
            error_code="reranker_unavailable",
        )


@pytest.mark.asyncio
async def test_fabricated_citation_handle_never_reaches_customer_as_valid_provenance() -> None:
    retrieval = UnavailableRetrieval()
    llm = ScriptedLLMClient([response("Company policy says [[K99]].")])

    result = await build_agent_graph().ainvoke(
        state("What is the policy?"),
        context=cast(Any, context(llm, retrieval)),
    )

    assert result["final_response"] == (
        "I'm unable to verify that information from the available company knowledge."
    )
    assert result["knowledge_evidence"] == []
