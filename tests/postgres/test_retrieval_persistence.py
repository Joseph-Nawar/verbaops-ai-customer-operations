from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from tests.postgres.test_retrieval_repository import TENANT_A, seed_retrieval_rows
from verbaops.conversations.persistence import AgentRun, Conversation, Message
from verbaops.knowledge.repository_tables import retrieval_candidates, retrieval_invocations
from verbaops.retrieval.models import RerankScore
from verbaops.retrieval.repository import RetrievalRepository
from verbaops.retrieval.service import RetrievalService, RetrievalStatus


class DeterministicEmbedding:
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[1.0] + [0.0] * 767 for _ in texts]


class DeterministicReranker:
    async def rerank(self, _query: str, candidates: Sequence[object]) -> list[RerankScore]:
        return [RerankScore(index=index, score=0.9) for index in range(len(candidates))]


@pytest.mark.postgres
@pytest.mark.contract
@pytest.mark.asyncio
async def test_retrieval_trace_and_candidate_stage_scores_persist(
    postgres_engine: AsyncEngine,
) -> None:
    await seed_retrieval_rows(postgres_engine)
    conversation_id = uuid4()
    user_message_id = uuid4()
    agent_run_id = uuid4()
    async with postgres_engine.begin() as connection:
        await connection.execute(
            insert(Conversation).values(
                id=conversation_id,
                tenant_id=TENANT_A,
                principal_id=uuid4(),
                customer_id=None,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await connection.execute(
            insert(Message).values(
                id=user_message_id,
                conversation_id=conversation_id,
                sequence=1,
                role="user",
                content="return window",
                created_at=datetime.now(UTC),
            )
        )
        await connection.execute(
            insert(AgentRun).values(
                id=agent_run_id,
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                assistant_message_id=None,
                status="running",
                graph_version="text-agent-v2",
                prompt_version="text-agent-system-v2",
                tool_schema_version="commerce-read-tools-v1",
                started_at=datetime.now(UTC),
                completed_at=None,
                error_code=None,
            )
        )

    service = RetrievalService(
        async_sessionmaker(postgres_engine, expire_on_commit=False),
        repository=RetrievalRepository(),
        embedding_client=DeterministicEmbedding(),
        reranker_client=DeterministicReranker(),
    )
    result = await service.retrieve(
        agent_run_id=agent_run_id,
        tenant_id=TENANT_A,
        query="return window",
    )

    assert result.status is RetrievalStatus.SUCCEEDED
    assert len(result.evidence) == 2
    async with postgres_engine.connect() as connection:
        invocation = (
            await connection.execute(
                select(
                    retrieval_invocations.c.status,
                    retrieval_invocations.c.sequence,
                    retrieval_invocations.c.dense_candidate_count,
                    retrieval_invocations.c.lexical_candidate_count,
                    retrieval_invocations.c.fused_candidate_count,
                    retrieval_invocations.c.reranked_candidate_count,
                    retrieval_invocations.c.selected_count,
                ).where(retrieval_invocations.c.id == result.invocation_id)
            )
        ).one()
        candidates = (
            await connection.execute(
                select(
                    retrieval_candidates.c.chunk_id,
                    retrieval_candidates.c.dense_rank,
                    retrieval_candidates.c.lexical_rank,
                    retrieval_candidates.c.rrf_rank,
                    retrieval_candidates.c.rerank_rank,
                    retrieval_candidates.c.rerank_score,
                    retrieval_candidates.c.selected,
                    retrieval_candidates.c.evidence_key,
                ).where(retrieval_candidates.c.retrieval_invocation_id == result.invocation_id)
            )
        ).all()
    assert invocation == ("succeeded", 1, 1, 2, 2, 2, 2)
    assert len(candidates) == 2
    assert {row.evidence_key for row in candidates} == {"K1", "K2"}
    assert all(row.selected and row.rerank_score == 0.9 for row in candidates)
