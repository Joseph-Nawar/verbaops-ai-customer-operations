from collections.abc import Sequence
from datetime import date
from typing import Any, cast
from uuid import UUID

import pytest

from verbaops.retrieval.models import (
    DenseHit,
    EvidenceGateScore,
    KnowledgeHit,
    LexicalHit,
    RerankScore,
)
from verbaops.retrieval.profile import PRODUCTION_RETRIEVAL_PROFILE
from verbaops.retrieval.service import RetrievalService, RetrievalStatus

RUN_ID = UUID("70000000-0000-0000-0000-000000000001")
TENANT_ID = UUID("60000000-0000-0000-0000-000000000001")


def knowledge(index: int) -> KnowledgeHit:
    return KnowledgeHit(
        chunk_id=UUID(int=index + 1),
        tenant_id=TENANT_ID,
        document_id=UUID(int=100 + index),
        version_id=UUID(int=200 + index),
        document_title=f"Policy {index}",
        document_slug=f"policy-{index}",
        document_version="2026.1",
        section="Section",
        effective_date=date(2026, 1, 1),
        language="en",
        content=f"Policy content {index}.",
    )


class FakeSession:
    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def begin(self) -> "FakeSession":
        return self

    async def connection(self) -> object:
        return object()


class FakeRepository:
    def __init__(self, candidates: Sequence[KnowledgeHit]) -> None:
        self.dense = [
            DenseHit(item, rank=index, score=0.9) for index, item in enumerate(candidates, 1)
        ]
        self.lexical = [
            LexicalHit(item, rank=index, score=0.8)
            for index, item in enumerate(reversed(candidates), 1)
        ]
        self.trace: dict[str, object] | None = None

    async def search_dense(self, _connection: object, **_kwargs: object) -> list[DenseHit]:
        return self.dense

    async def search_lexical(self, _connection: object, **_kwargs: object) -> list[LexicalHit]:
        return self.lexical

    async def persist_trace(self, _connection: object, **kwargs: object) -> None:
        self.trace = kwargs


class FakeEmbedding:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.texts.extend(texts)
        return [[0.25] * 768 for _ in texts]


class FakeReranker:
    def __init__(self, score: float) -> None:
        self.score = score

    async def rerank(self, _query: str, candidates: Sequence[object]) -> list[RerankScore]:
        return [
            RerankScore(index=index, score=self.score - index * 0.01)
            for index in range(len(candidates))
        ]


class FailingEmbedding:
    async def embed(self, _texts: Sequence[str]) -> list[list[float]]:
        raise RuntimeError("embedding unavailable")


class ExplodingReranker:
    async def rerank(self, _query: str, _candidates: Sequence[object]) -> list[RerankScore]:
        raise AssertionError("production hybrid RRF must not call the reranker")


class FixedEvidenceGateScorer:
    def __init__(self, confidence: float) -> None:
        self.confidence = confidence
        self.candidate_ids: list[UUID] = []

    async def score(
        self,
        _query: str,
        query_embedding: Sequence[float],
        candidates: Sequence[Any],
    ) -> EvidenceGateScore:
        assert len(query_embedding) == 768
        self.candidate_ids = [candidate.chunk.chunk_id for candidate in candidates]
        return EvidenceGateScore(
            confidence=self.confidence,
            candidate_scores=(self.confidence,) * len(candidates),
            component_latency_ms={"candidate_score": 1.25},
        )


def session_factory() -> FakeSession:
    return FakeSession()


@pytest.mark.asyncio
async def test_production_profile_uses_hybrid_rrf_without_reranker_dependency() -> None:
    repository = FakeRepository([knowledge(0), knowledge(1)])
    service = RetrievalService(
        cast(Any, session_factory),
        repository=cast(Any, repository),
        embedding_client=FakeEmbedding(),
        reranker_client=ExplodingReranker(),
        profile=PRODUCTION_RETRIEVAL_PROFILE,
    )

    result = await service.retrieve(agent_run_id=RUN_ID, tenant_id=TENANT_ID, query="warranty")

    assert result.status is RetrievalStatus.SUCCEEDED
    assert len(result.evidence) == 2
    assert repository.trace is not None
    assert repository.trace["retrieval_version"] == "knowledge-retrieval-v1.1"


@pytest.mark.asyncio
async def test_gate_scorer_receives_exact_final_five_only() -> None:
    candidates = [knowledge(index) for index in range(8)]
    repository = FakeRepository(candidates)
    scorer = FixedEvidenceGateScorer(confidence=0.05)
    service = RetrievalService(
        cast(Any, session_factory),
        repository=cast(Any, repository),
        embedding_client=FakeEmbedding(),
        reranker_client=ExplodingReranker(),
        profile=PRODUCTION_RETRIEVAL_PROFILE,
        evidence_gate_scorer=scorer,
        evidence_gate_threshold=0.04,
    )

    result = await service.retrieve(agent_run_id=RUN_ID, tenant_id=TENANT_ID, query="warranty")

    assert result.status is RetrievalStatus.SUCCEEDED
    assert len(scorer.candidate_ids) == 5
    assert [item.chunk_id for item in result.evidence] == scorer.candidate_ids
    assert result.gate_candidate_scores == (0.05,) * 5


@pytest.mark.asyncio
async def test_failed_gate_score_fails_closed_without_supplied_evidence() -> None:
    class FailingGateScorer:
        async def score(
            self,
            _query: str,
            _query_embedding: Sequence[float],
            _candidates: Sequence[Any],
        ) -> EvidenceGateScore:
            raise RuntimeError("scoring failure must not admit evidence")

    repository = FakeRepository([knowledge(0)])
    service = RetrievalService(
        cast(Any, session_factory),
        repository=cast(Any, repository),
        embedding_client=FakeEmbedding(),
        reranker_client=ExplodingReranker(),
        profile=PRODUCTION_RETRIEVAL_PROFILE,
        evidence_gate_scorer=FailingGateScorer(),
        evidence_gate_threshold=0.01,
    )

    result = await service.retrieve(agent_run_id=RUN_ID, tenant_id=TENANT_ID, query="warranty")

    assert result.status is RetrievalStatus.FAILED
    assert result.top_score is None
    assert result.evidence == ()
    assert repository.trace is not None
    assert repository.trace["error_code"] == "evidence_gate_unavailable"
    assert repository.trace["selected_count"] == 0
    assert repository.trace["strategy"] == "hybrid_rrf"
    assert repository.trace["reranked_candidate_count"] == 0


@pytest.mark.asyncio
async def test_retrieval_service_formats_query_fuses_reranks_and_persists_selected_evidence() -> (
    None
):
    repository = FakeRepository([knowledge(0), knowledge(1)])
    embedding = FakeEmbedding()
    service = RetrievalService(
        cast(Any, session_factory),
        repository=cast(Any, repository),
        embedding_client=embedding,
        reranker_client=FakeReranker(0.9),
    )

    result = await service.retrieve(
        agent_run_id=RUN_ID, tenant_id=TENANT_ID, query=" return window "
    )

    assert result.status is RetrievalStatus.SUCCEEDED
    assert embedding.texts == ["query: return window"]
    assert [item.evidence_key for item in result.evidence] == ["K1", "K2"]
    assert result.invocation_id is not None
    assert repository.trace is not None
    assert repository.trace["dense_candidate_count"] == 2
    assert repository.trace["lexical_candidate_count"] == 2
    assert repository.trace["fused_candidate_count"] == 2
    assert repository.trace["reranked_candidate_count"] == 2
    assert repository.trace["selected_count"] == 2


@pytest.mark.asyncio
async def test_retrieval_service_abstains_when_top_score_is_below_provisional_threshold() -> None:
    repository = FakeRepository([knowledge(0)])
    service = RetrievalService(
        cast(Any, session_factory),
        repository=cast(Any, repository),
        embedding_client=FakeEmbedding(),
        reranker_client=FakeReranker(0.49),
    )

    result = await service.retrieve(agent_run_id=RUN_ID, tenant_id=TENANT_ID, query="warranty")

    assert result.status is RetrievalStatus.INSUFFICIENT
    assert result.evidence == ()
    assert repository.trace is not None
    assert repository.trace["selected_count"] == 0


@pytest.mark.asyncio
async def test_optional_gate_scorer_overrides_only_evidence_acceptance_and_keeps_rrf_order() -> (
    None
):
    repository = FakeRepository([knowledge(0), knowledge(1)])
    scorer = FixedEvidenceGateScorer(confidence=0.05)
    service = RetrievalService(
        cast(Any, session_factory),
        repository=cast(Any, repository),
        embedding_client=FakeEmbedding(),
        reranker_client=ExplodingReranker(),
        profile=PRODUCTION_RETRIEVAL_PROFILE,
        evidence_gate_scorer=scorer,
        evidence_gate_threshold=0.04,
    )

    result = await service.retrieve(agent_run_id=RUN_ID, tenant_id=TENANT_ID, query="warranty")

    assert result.status is RetrievalStatus.SUCCEEDED
    assert scorer.candidate_ids == [item.chunk_id for item in [knowledge(0), knowledge(1)]]
    assert [item.chunk_id for item in result.evidence] == scorer.candidate_ids
    assert result.top_score == 0.05
    assert result.gate_score_components_ms == {"candidate_score": 1.25}
    assert repository.trace is not None
    assert repository.trace["top_score"] == 0.05
    assert repository.trace["strategy"] == "hybrid_rrf"
    assert repository.trace["retrieval_version"] == "knowledge-retrieval-v1.1"


@pytest.mark.asyncio
async def test_retrieval_service_returns_no_evidence_when_embedding_is_unavailable() -> None:
    repository = FakeRepository([knowledge(0)])
    service = RetrievalService(
        cast(Any, session_factory),
        repository=cast(Any, repository),
        embedding_client=FailingEmbedding(),
        reranker_client=FakeReranker(0.9),
    )

    result = await service.retrieve(agent_run_id=RUN_ID, tenant_id=TENANT_ID, query="warranty")

    assert result.status is RetrievalStatus.UNAVAILABLE
    assert result.evidence == ()
