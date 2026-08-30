"""Real PostgreSQL execution adapter for the frozen RAG benchmark."""

from __future__ import annotations

from time import perf_counter
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from verbaops.evaluation.rag_runner import (
    DEFAULT_PARAMETERS,
    FrozenRetrievalParameters,
    RetrievalRun,
    RetrievalStrategy,
    retrieve_frozen_strategy,
)
from verbaops.knowledge.embeddings import EmbeddingProtocolError
from verbaops.knowledge.profiles import EMBEDDING_DIMENSION, EMBEDDING_PROFILE, format_query
from verbaops.retrieval.models import DenseHit, LexicalHit
from verbaops.retrieval.repository import RetrievalRepository


class PostgresRagAdapter:
    """Execute all benchmark strategies through the production M5B primitives."""

    provider_mode = "real"

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        tenant_id: Any,
        embedding_client: Any,
        reranker_client: Any,
        repository: RetrievalRepository | None = None,
        language: str = "en",
        parameters: FrozenRetrievalParameters = DEFAULT_PARAMETERS,
    ) -> None:
        self._session_factory = session_factory
        self._tenant_id = tenant_id
        self._embedding_client = embedding_client
        self._reranker_client = reranker_client
        self._repository = repository or RetrievalRepository()
        self._language = language
        self._parameters = parameters

    async def execute(self, case: Any, strategy: RetrievalStrategy) -> RetrievalRun:
        stage: dict[str, float] = {}
        dense: list[DenseHit] = []
        lexical: list[LexicalHit] = []
        vectors: list[list[float]] = []
        needs_dense = strategy in (
            RetrievalStrategy.DENSE,
            RetrievalStrategy.HYBRID_RRF,
            RetrievalStrategy.HYBRID_RRF_RERANK,
        )
        if needs_dense:
            embedding_started = perf_counter()
            vectors = await self._embedding_client.embed([format_query(case.query)])
            if len(vectors) != 1 or len(vectors[0]) != EMBEDDING_DIMENSION:
                raise EmbeddingProtocolError("benchmark query embedding was not 768-dimensional")
            stage["embedding"] = _elapsed(embedding_started)

        async with self._session_factory() as session, session.begin():
            connection = await session.connection()
            if needs_dense:
                dense_started = perf_counter()
                dense = await self._repository.search_dense(
                    connection,
                    tenant_id=self._tenant_id,
                    vector=vectors[0],
                    embedding_profile=EMBEDDING_PROFILE,
                    language=self._language,
                    limit=self._parameters.dense_limit,
                )
                stage["dense"] = _elapsed(dense_started)
            if strategy in (
                RetrievalStrategy.LEXICAL,
                RetrievalStrategy.HYBRID_RRF,
                RetrievalStrategy.HYBRID_RRF_RERANK,
            ):
                lexical_started = perf_counter()
                lexical = await self._repository.search_lexical(
                    connection,
                    tenant_id=self._tenant_id,
                    query=case.query,
                    language=self._language,
                    limit=self._parameters.lexical_limit,
                )
                stage["lexical"] = _elapsed(lexical_started)

        ranked = await retrieve_frozen_strategy(
            case.query,
            dense=dense,
            lexical=lexical,
            strategy=strategy,
            rerank=(
                self._reranker_client.rerank
                if strategy is RetrievalStrategy.HYBRID_RRF_RERANK
                else None
            ),
            parameters=self._parameters,
        )
        for name in ("fusion", "rerank"):
            if name in ranked.stage_latency_ms:
                stage[name] = ranked.stage_latency_ms[name]
        stage["total"] = round(sum(stage.values()), 6)
        return RetrievalRun(
            strategy=ranked.strategy,
            candidates=ranked.candidates,
            top_score=ranked.top_score,
            stage_latency_ms=stage,
        )


def _elapsed(started: float) -> float:
    return round(max(0.0, (perf_counter() - started) * 1000), 6)


__all__ = ["PostgresRagAdapter"]
