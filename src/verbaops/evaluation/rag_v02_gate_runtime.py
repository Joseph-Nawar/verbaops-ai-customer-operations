"""Real, DEV-only M5D gate measurements over frozen hybrid-RRF candidates."""

from __future__ import annotations

from time import perf_counter
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from verbaops.evaluation.rag_runner import (
    DEFAULT_PARAMETERS,
    RetrievalStrategy,
    retrieve_frozen_strategy,
)
from verbaops.knowledge.embeddings import EmbeddingProtocolError
from verbaops.knowledge.profiles import EMBEDDING_DIMENSION, EMBEDDING_PROFILE, format_query
from verbaops.retrieval.evidence_gate import (
    DenseSimilarityGateScorer,
    EvidenceGate,
    RrfTopScoreGateScorer,
    TopEvidenceCrossEncoderGateScorer,
)
from verbaops.retrieval.models import DenseHit, LexicalHit
from verbaops.retrieval.repository import RetrievalRepository


class PostgresM5dGateAdapter:
    """Measure G0/G1/G2 without changing the single hybrid-RRF candidate order."""

    provider_mode = "real"

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        tenant_id: Any,
        embedding_client: Any,
        reranker_client: Any,
        repository: RetrievalRepository | None = None,
        parameters: Any = DEFAULT_PARAMETERS,
    ) -> None:
        self._session_factory = session_factory
        self._tenant_id = tenant_id
        self._embedding_client = embedding_client
        self._reranker_client = reranker_client
        self._repository = repository or RetrievalRepository()
        self._parameters = parameters
        self._g0 = RrfTopScoreGateScorer()
        self._g1 = DenseSimilarityGateScorer(session_factory, repository=self._repository)
        self._g2 = TopEvidenceCrossEncoderGateScorer(reranker_client)

    async def execute(self, case: Any) -> dict[str, object]:
        stage: dict[str, float] = {}
        embedding_started = perf_counter()
        vectors = await self._embedding_client.embed([format_query(case.query)])
        if len(vectors) != 1 or len(vectors[0]) != EMBEDDING_DIMENSION:
            raise EmbeddingProtocolError("M5D query embedding was not 768-dimensional")
        stage["embedding"] = _elapsed(embedding_started)

        async with self._session_factory() as session, session.begin():
            connection = await session.connection()
            dense_started = perf_counter()
            dense: list[DenseHit] = await self._repository.search_dense(
                connection,
                tenant_id=self._tenant_id,
                vector=vectors[0],
                embedding_profile=EMBEDDING_PROFILE,
                language=case.language,
                limit=self._parameters.dense_limit,
            )
            stage["dense"] = _elapsed(dense_started)
            lexical_started = perf_counter()
            lexical: list[LexicalHit] = await self._repository.search_lexical(
                connection,
                tenant_id=self._tenant_id,
                query=case.query,
                language=case.language,
                limit=self._parameters.lexical_limit,
            )
            stage["lexical"] = _elapsed(lexical_started)

        ranked = await retrieve_frozen_strategy(
            case.query,
            dense=dense,
            lexical=lexical,
            strategy=RetrievalStrategy.HYBRID_RRF,
            parameters=self._parameters,
        )
        stage["fusion"] = ranked.stage_latency_ms["fusion"]
        base_components = {
            "hybrid_retrieval": round(sum(stage.values()), 6),
        }

        gate_results: dict[str, dict[str, object]] = {}
        for gate, scorer in (
            (EvidenceGate.G0_CURRENT_RRF, self._g0),
            (EvidenceGate.G1_DENSE_SIMILARITY, self._g1),
            (EvidenceGate.G2_TOP_EVIDENCE_CROSS_ENCODER, self._g2),
        ):
            score = await scorer.score(case.query, vectors[0], ranked.candidates)
            components = dict(base_components)
            components.update(score.component_latency_ms)
            gate_results[gate.value] = {
                "confidence": score.confidence,
                "candidate_scores": list(score.candidate_scores),
                "latency_components_ms": components,
            }

        return {
            "case_id": case.case_id,
            "answerable": case.answerable,
            "ranked_locators": [candidate_locator(candidate) for candidate in ranked.candidates],
            "candidate_scores": {
                gate: result["candidate_scores"] for gate, result in gate_results.items()
            },
            "gate_results": gate_results,
            "retrieval_stage_latency_ms": stage,
        }


def candidate_locator(candidate: Any) -> str:
    chunk = candidate.chunk
    return f"{chunk.document_slug}|{chunk.document_version}|{chunk.section}|{chunk.chunk_index}"


def _elapsed(started: float) -> float:
    return round(max(0.0, (perf_counter() - started) * 1000), 6)


__all__ = ["PostgresM5dGateAdapter"]
