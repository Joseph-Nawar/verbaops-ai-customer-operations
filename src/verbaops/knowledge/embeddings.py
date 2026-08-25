"""Application-owned LiteLLM embedding gateway contract."""

from __future__ import annotations

from collections.abc import Sequence

import httpx

from verbaops.config.settings import LLMSettings
from verbaops.llm.models import CapabilityAlias

EMBEDDING_DIMENSION = 768


class EmbeddingProtocolError(RuntimeError):
    """The gateway response is absent, malformed, partial, or wrong-sized."""

    def __init__(self, message: str = "embedding gateway response was invalid") -> None:
        super().__init__(message)


class EmbeddingClient:
    """Call the OpenAI-compatible embedding endpoint without loading a model."""

    def __init__(self, settings: LLMSettings, http_client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http_client = http_client
        self._endpoint = f"{settings.base_url.rstrip('/')}/embeddings"

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a complete batch and reject any response that is not complete."""

        if not texts:
            return []
        try:
            response = await self._http_client.post(
                self._endpoint,
                headers={"Authorization": f"Bearer {self._settings.api_key.get_secret_value()}"},
                json={"model": CapabilityAlias.EMBEDDING_MULTILINGUAL.value, "input": list(texts)},
                timeout=self._settings.timeout_seconds,
            )
        except httpx.HTTPError as error:
            raise EmbeddingProtocolError() from error
        if response.status_code < 200 or response.status_code >= 300:
            raise EmbeddingProtocolError()
        try:
            payload = response.json()
        except (UnicodeDecodeError, ValueError) as error:
            raise EmbeddingProtocolError() from error
        vectors = self._parse_vectors(payload, len(texts))
        return vectors

    @staticmethod
    def _parse_vectors(payload: object, expected_count: int) -> list[list[float]]:
        if not isinstance(payload, dict):
            raise EmbeddingProtocolError()
        data = payload.get("data")
        if not isinstance(data, list) or len(data) != expected_count:
            raise EmbeddingProtocolError()
        ordered: list[list[float] | None] = [None] * expected_count
        for item in data:
            if not isinstance(item, dict):
                raise EmbeddingProtocolError()
            index = item.get("index")
            values = item.get("embedding")
            if isinstance(index, bool) or not isinstance(index, int):
                raise EmbeddingProtocolError()
            if not 0 <= index < expected_count or ordered[index] is not None:
                raise EmbeddingProtocolError()
            if not isinstance(values, list) or len(values) != EMBEDDING_DIMENSION:
                raise EmbeddingProtocolError()
            if any(
                isinstance(value, bool) or not isinstance(value, int | float) for value in values
            ):
                raise EmbeddingProtocolError()
            ordered[index] = [float(value) for value in values]
        if any(vector is None for vector in ordered):
            raise EmbeddingProtocolError()
        return [vector for vector in ordered if vector is not None]


def deterministic_embedding(text: str, *, dimension: int = EMBEDDING_DIMENSION) -> list[float]:
    """Return a stable provider-free vector for local contract tests."""

    import hashlib

    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [((digest[index % len(digest)] / 255.0) * 2.0) - 1.0 for index in range(dimension)]
