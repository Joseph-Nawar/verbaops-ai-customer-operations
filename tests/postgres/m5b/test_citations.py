from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, insert
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from verbaops.conversations.domain import ConversationScope
from verbaops.conversations.service import ConversationService
from verbaops.knowledge.repository_tables import (
    knowledge_chunks,
    knowledge_documents,
    knowledge_versions,
    retrieval_invocations,
)
from verbaops.retrieval.grounding import CitationFinalizer
from verbaops.retrieval.models import RetrievalEvidence

TENANT = UUID("60000000-0000-0000-0000-000000000011")
SCOPE = ConversationScope(TENANT, UUID("60000000-0000-0000-0000-000000000012"))


@pytest.mark.postgres
@pytest.mark.contract
@pytest.mark.asyncio
async def test_completion_persists_db_resolved_citation_snapshot_in_one_transaction(
    postgres_engine: AsyncEngine,
) -> None:
    service = ConversationService(async_sessionmaker(postgres_engine, expire_on_commit=False))
    conversation = await service.create_conversation(SCOPE)
    started = await service.start_turn(
        SCOPE,
        conversation.id,
        "What is the return window?",
        graph_version="text-agent-v2",
        prompt_version="text-agent-system-v2",
        tool_schema_version="commerce-read-tools-v1",
    )
    document_id = uuid4()
    version_id = uuid4()
    chunk_id = uuid4()
    invocation_id = uuid4()
    async with postgres_engine.begin() as connection:
        await connection.execute(
            insert(knowledge_documents).values(
                id=document_id,
                tenant_id=TENANT,
                slug="returns-policy-citation",
                title="Returns Policy",
                document_type="policy",
                language="en",
            )
        )
        await connection.execute(
            insert(knowledge_versions).values(
                id=version_id,
                document_id=document_id,
                version="2026.1",
                effective_date=date(2026, 1, 1),
                status="active",
                source_content="# Return Window\n30 days.",
                source_hash="b" * 64,
                embedding_profile="multilingual-e5-base-v1",
                embedding_model="intfloat/multilingual-e5-base",
            )
        )
        await connection.execute(
            insert(knowledge_chunks).values(
                id=chunk_id,
                version_id=version_id,
                tenant_id=TENANT,
                document_id=document_id,
                document_version="2026.1",
                section="Return Window",
                language="en",
                effective_date=date(2026, 1, 1),
                chunk_index=0,
                content="Return window is 30 days.",
                content_hash="c" * 64,
                embedding=[0.0] * 768,
                search_vector=func.to_tsvector("english", "Return window is 30 days."),
            )
        )
        await connection.execute(
            insert(retrieval_invocations).values(
                id=invocation_id,
                agent_run_id=started.agent_run.id,
                tenant_id=TENANT,
                sequence=1,
                retrieval_version="knowledge-retrieval-v1",
                strategy="hybrid_rrf",
                language="en",
                status="succeeded",
                dense_candidate_count=1,
                lexical_candidate_count=1,
                fused_candidate_count=1,
                reranked_candidate_count=1,
                selected_count=1,
                top_score=0.9,
                latency_ms=1.0,
                embedding_model="intfloat/multilingual-e5-base",
                reranker_model="cross-encoder/mmarco-mMiniLMv2-L12-H384-v1",
                error_code=None,
                created_at=datetime.now(UTC),
            )
        )

    grounded = CitationFinalizer().finalize(
        "Return within 30 days [[K1]].",
        [
            RetrievalEvidence(
                evidence_key="K1",
                chunk_id=chunk_id,
                document_id=document_id,
                version_id=version_id,
                document_title="DB title, not assistant title",
                document_slug="returns-policy-citation",
                document_version="2026.1",
                section="Return Window",
                effective_date=date(2026, 1, 1),
                content="Return window is 30 days.",
            )
        ],
    )
    completion = await service.complete_turn(
        SCOPE,
        conversation.id,
        started.agent_run.id,
        grounded.content,
        retrieval_invocation_id=invocation_id,
        citations=grounded.citations,
    )

    assert completion.assistant_message.content == "Return within 30 days [1]."
    assert completion.assistant_message.citations[0].document_slug == "returns-policy-citation"
    messages = await service.list_messages(SCOPE, conversation.id)
    citation = messages[-1].citations[0]
    assert citation.document_title == "DB title, not assistant title"
    assert citation.document_slug == "returns-policy-citation"
    assert citation.citation_ordinal == 1
    assert citation.evidence_key == "K1"
