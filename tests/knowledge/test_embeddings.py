import json
from collections.abc import Callable

import httpx
import pytest
from pydantic import SecretStr

from verbaops.config.settings import LLMSettings
from verbaops.knowledge.embeddings import EmbeddingClient, EmbeddingProtocolError


def make_client(handler: Callable[[httpx.Request], httpx.Response]) -> EmbeddingClient:
    return EmbeddingClient(
        LLMSettings(base_url="http://gateway.test/v1", api_key=SecretStr("test-key")),
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def vector(seed: int) -> list[float]:
    return [float(seed)] * 768


@pytest.mark.asyncio
async def test_embedding_client_posts_alias_and_accepts_deterministic_768_vectors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://gateway.test/v1/embeddings"
        assert json.loads(request.content) == {
            "model": "embedding-multilingual",
            "input": ["first", "second"],
        }
        return httpx.Response(
            200,
            json={
                "data": [
                    {"object": "embedding", "index": 0, "embedding": vector(1)},
                    {"object": "embedding", "index": 1, "embedding": vector(2)},
                ],
                "model": "deterministic-embedding",
            },
        )

    embeddings = await make_client(handler).embed(["first", "second"])

    assert len(embeddings) == 2
    assert len(embeddings[0]) == 768
    assert embeddings[0] == embeddings[0]
    assert embeddings[0] != embeddings[1]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": [{"index": 0, "embedding": vector(1)}]},
        {"data": [{"index": 0, "embedding": [1.0]}]},
        {"data": [{"index": 0, "embedding": vector(1)}, {"index": 0, "embedding": vector(2)}]},
    ],
)
async def test_embedding_client_rejects_malformed_missing_wrong_dimension_or_partial_response(
    payload: dict[str, object],
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    with pytest.raises(EmbeddingProtocolError):
        await make_client(handler).embed(["first", "second"])
