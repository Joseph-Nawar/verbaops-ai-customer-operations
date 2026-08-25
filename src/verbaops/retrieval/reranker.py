"""Strict client for the text-embeddings-inference rerank endpoint."""

from __future__ import annotations

import math
from collections.abc import Sequence

import httpx

from verbaops.retrieval.models import FusedCandidate, RerankScore


class RerankerProtocolError(RuntimeError):
    """The TEI reranker response is unavailable or malformed."""


class RerankerClient:
    """Call TEI directly and reject partial or ambiguous rankings."""

    def __init__(self, base_url: str, http_client: httpx.AsyncClient) -> None:
        self._endpoint = f"{base_url.rstrip('/')}/rerank"
        self._http_client = http_client

    async def rerank(
        self, query: str, candidates: Sequence[FusedCandidate]
    ) -> list[RerankScore]:
        if not candidates:
            return []
        try:
            response = await self._http_client.post(
                self._endpoint,
                json={
                    "query": query,
                    "texts": [candidate.chunk.content for candidate in candidates],
                    "raw_scores": False,
                },
            )
        except httpx.HTTPError as error:
            raise RerankerProtocolError() from error
        if response.status_code < 200 or response.status_code >= 300:
            raise RerankerProtocolError()
        try:
            payload = response.json()
        except (UnicodeDecodeError, ValueError) as error:
            raise RerankerProtocolError() from error
        return self._parse_scores(payload, len(candidates))

    @staticmethod
    def _parse_scores(payload: object, expected_count: int) -> list[RerankScore]:
        if not isinstance(payload, list) or len(payload) != expected_count:
            raise RerankerProtocolError()
        scores: list[RerankScore] = []
        indexes: set[int] = set()
        for item in payload:
            if not isinstance(item, dict):
                raise RerankerProtocolError()
            index = item.get("index")
            score = item.get("score")
            if isinstance(index, bool) or not isinstance(index, int):
                raise RerankerProtocolError()
            if not 0 <= index < expected_count or index in indexes:
                raise RerankerProtocolError()
            if isinstance(score, bool) or not isinstance(score, int | float):
                raise RerankerProtocolError()
            numeric_score = float(score)
            if not math.isfinite(numeric_score):
                raise RerankerProtocolError()
            indexes.add(index)
            scores.append(RerankScore(index=index, score=numeric_score))
        if indexes != set(range(expected_count)):
            raise RerankerProtocolError()
        return sorted(scores, key=lambda item: item.index)


__all__ = ["RerankerClient", "RerankerProtocolError"]
