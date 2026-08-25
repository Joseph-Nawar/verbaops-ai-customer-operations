import os

import httpx
import pytest
from pydantic import SecretStr

from verbaops.config.settings import LLMSettings
from verbaops.knowledge.embeddings import EMBEDDING_DIMENSION, EmbeddingClient


@pytest.mark.llm_gateway_contract
@pytest.mark.asyncio
async def test_real_deterministic_gateway_returns_provider_free_768_embeddings() -> None:
    settings = LLMSettings(
        base_url=os.environ["VERBAOPS_LLM__BASE_URL"],
        api_key=SecretStr(os.environ.get("VERBAOPS_LLM__API_KEY", "sk-test-gateway")),
        timeout_seconds=2.0,
    )
    async with httpx.AsyncClient() as client:
        vectors = await EmbeddingClient(settings, client).embed(
            ["shipping policy", "shipping policy"]
        )
    assert len(vectors) == 2
    assert all(len(vector) == EMBEDDING_DIMENSION for vector in vectors)
    assert vectors[0] == vectors[1]
