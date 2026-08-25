import json
from datetime import date
from uuid import UUID

import httpx
import pytest

from verbaops.retrieval.models import FusedCandidate, KnowledgeHit
from verbaops.retrieval.reranker import RerankerClient, RerankerProtocolError


def candidate(index: int) -> FusedCandidate:
    chunk = KnowledgeHit(
        chunk_id=UUID(int=index + 1),
        tenant_id=UUID(int=1),
        document_id=UUID(int=2),
        version_id=UUID(int=3),
        document_title="Returns Policy",
        document_slug="returns-policy",
        document_version="2026.1",
        section="Return Window",
        effective_date=date(2026, 1, 1),
        language="en",
        content=f"candidate {index}",
    )
    return FusedCandidate(
        chunk=chunk,
        dense_rank=None,
        dense_score=None,
        lexical_rank=None,
        lexical_score=None,
        rrf_rank=index + 1,
        rrf_score=1.0 / (61 + index),
    )


@pytest.mark.asyncio
async def test_reranker_posts_strict_tei_request_and_returns_scores() -> None:
    candidates = [candidate(0), candidate(1)]

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://reranker.test/rerank"
        assert json.loads(request.content) == {
            "query": "return window",
            "texts": ["candidate 0", "candidate 1"],
            "raw_scores": False,
        }
        return httpx.Response(200, json=[{"index": 1, "score": 0.8}, {"index": 0, "score": 0.9}])

    client = RerankerClient(
        "http://reranker.test",
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    scores = await client.rerank("return window", candidates)

    assert [(item.index, item.score) for item in scores] == [(0, 0.9), (1, 0.8)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        [],
        [{"index": 0, "score": 0.9}],
        [{"index": 0, "score": 0.9}, {"index": 0, "score": 0.8}],
        [{"index": 2, "score": 0.9}, {"index": 1, "score": 0.8}],
        [{"index": 0, "score": "high"}, {"index": 1, "score": 0.8}],
    ],
)
async def test_reranker_rejects_partial_duplicate_invalid_or_non_numeric_responses(
    payload: list[dict[str, object]],
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client = RerankerClient(
        "http://reranker.test",
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(RerankerProtocolError):
        await client.rerank("return window", [candidate(0), candidate(1)])

