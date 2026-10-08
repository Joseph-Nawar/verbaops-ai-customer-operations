"""FastAPI lifespan ownership for external runtime resources."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta

import httpx
from fastapi import FastAPI
from redis.asyncio import Redis

from verbaops.actions.decisions import ActionDecisionService
from verbaops.actions.executor import ActionExecutor
from verbaops.actions.proposals import ActionProposalService
from verbaops.actions.reconciliation import ActionReconciler
from verbaops.actions.repository import ActionRepository
from verbaops.actions.transitions import ActionTransitionService
from verbaops.agent.evaluation import GroundingCandidate
from verbaops.agent.runtime import AgentRuntime
from verbaops.api.dependencies import ApplicationDependencies
from verbaops.cache.redis import close_redis, create_redis_client
from verbaops.commerce.client import CommerceClient
from verbaops.conversations.service import ConversationService
from verbaops.db.resources import (
    DatabaseResources,
    create_database_resources,
    dispose_database_resources,
)
from verbaops.evaluation.p4_trace import P4TraceStore
from verbaops.evaluation.p5_trace import P5TraceStore
from verbaops.knowledge.embeddings import EmbeddingClient
from verbaops.knowledge.repository import KnowledgeRepository
from verbaops.knowledge.service import KnowledgeService
from verbaops.llm.litellm import LiteLLMClient
from verbaops.retrieval.evidence_gate import (
    DenseSimilarityGateScorer,
    EvidenceGate,
    RrfTopScoreGateScorer,
    TopEvidenceCrossEncoderGateScorer,
)
from verbaops.retrieval.grounding import CitationFinalizer
from verbaops.retrieval.profile import PRODUCTION_RETRIEVAL_PROFILE
from verbaops.retrieval.reranker import RerankerClient
from verbaops.retrieval.service import EvidenceGateScorer, RetrievalService
from verbaops.voice.livekit import LiveKitTokenIssuer
from verbaops.voice.service import VoiceSessionService


@dataclass(frozen=True, slots=True)
class RuntimeResources:
    """Mutable I/O resources owned by one application lifespan."""

    database: DatabaseResources | None = field(repr=False)
    redis: Redis | None = field(repr=False)
    llm_http_client: httpx.AsyncClient | None = field(default=None, repr=False)
    commerce_http_client: httpx.AsyncClient | None = field(default=None, repr=False)
    rag_http_client: httpx.AsyncClient | None = field(default=None, repr=False)
    llm_client: LiteLLMClient | None = field(default=None, repr=False)
    commerce_client: CommerceClient | None = field(default=None, repr=False)
    conversation_service: ConversationService | None = field(default=None, repr=False)
    action_proposal_service: ActionProposalService | None = field(default=None, repr=False)
    action_executor: ActionExecutor | None = field(default=None, repr=False)
    action_decision_service: ActionDecisionService | None = field(default=None, repr=False)
    action_reconciler: ActionReconciler | None = field(default=None, repr=False)
    agent_runtime: AgentRuntime | None = field(default=None, repr=False)
    embedding_client: EmbeddingClient | None = field(default=None, repr=False)
    knowledge_service: KnowledgeService | None = field(default=None, repr=False)
    reranker_client: RerankerClient | None = field(default=None, repr=False)
    retrieval_service: RetrievalService | None = field(default=None, repr=False)
    voice_session_service: VoiceSessionService | None = field(default=None, repr=False)
    voice_token_issuer: LiveKitTokenIssuer | None = field(default=None, repr=False)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create configured resources and guarantee cleanup, including partial startup."""

    dependencies = getattr(app.state, "verbaops_dependencies", None)
    if not isinstance(dependencies, ApplicationDependencies):
        raise RuntimeError("VerbaOps AI application dependencies are not configured")

    database: DatabaseResources | None = None
    redis: Redis | None = None
    llm_http_client: httpx.AsyncClient | None = None
    commerce_http_client: httpx.AsyncClient | None = None
    rag_http_client: httpx.AsyncClient | None = None
    llm_client: LiteLLMClient | None = None
    commerce_client: CommerceClient | None = None
    conversation_service: ConversationService | None = None
    action_proposal_service: ActionProposalService | None = None
    action_executor: ActionExecutor | None = None
    action_decision_service: ActionDecisionService | None = None
    action_reconciler: ActionReconciler | None = None
    agent_runtime: AgentRuntime | None = None
    embedding_client: EmbeddingClient | None = None
    knowledge_service: KnowledgeService | None = None
    reranker_client: RerankerClient | None = None
    retrieval_service: RetrievalService | None = None
    voice_session_service: VoiceSessionService | None = None
    voice_token_issuer = LiveKitTokenIssuer(dependencies.settings.voice)
    try:
        if (
            dependencies.settings.database.url is not None
            and dependencies.settings.database.url.get_secret_value().strip()
        ):
            database = create_database_resources(dependencies.settings)
        if (
            dependencies.settings.redis.url is not None
            and dependencies.settings.redis.url.get_secret_value().strip()
        ):
            redis = create_redis_client(dependencies.settings)
        llm_http_client = httpx.AsyncClient()
        commerce_http_client = httpx.AsyncClient()
        llm_client = LiteLLMClient(dependencies.settings.llm, llm_http_client)
        embedding_client = EmbeddingClient(dependencies.settings.llm, llm_http_client)
        evaluation_profile = dependencies.evaluation_profile
        uses_evaluation_reranker = (
            evaluation_profile is not None
            and evaluation_profile.evidence_gate is EvidenceGate.G2_TOP_EVIDENCE_CROSS_ENCODER
        )
        if PRODUCTION_RETRIEVAL_PROFILE.uses_reranker or uses_evaluation_reranker:
            rag_http_client = httpx.AsyncClient()
            reranker_client = RerankerClient(
                dependencies.settings.rag.reranker_url,
                rag_http_client,
                timeout_seconds=dependencies.settings.rag.timeout_seconds,
            )
        commerce_client = CommerceClient(dependencies.settings.commerce, commerce_http_client)
        if database is not None:
            action_repository = ActionRepository(database.session_factory)
            conversation_service = ConversationService(
                database.session_factory, action_repository=action_repository
            )
            voice_session_service = VoiceSessionService(
                database.session_factory,
                conversation_service=conversation_service,
                token_issuer=voice_token_issuer,
                livekit_url=dependencies.settings.voice.livekit_url,
                session_ttl=timedelta(seconds=dependencies.settings.voice.session_ttl_seconds),
                token_ttl=timedelta(seconds=dependencies.settings.voice.token_ttl_seconds),
                stt_provider=dependencies.settings.voice.stt_provider,
                tts_provider=dependencies.settings.voice.tts_provider,
            )
            action_transition_service = ActionTransitionService(database.session_factory)
            action_proposal_service = ActionProposalService(
                commerce_client,
                action_repository,
                action_transition_service,
            )
            action_executor = ActionExecutor(
                commerce_client=commerce_client,
                transition_service=action_transition_service,
                freshness_service=action_proposal_service,
            )
            action_decision_service = ActionDecisionService(
                transition_service=action_transition_service,
                freshness_service=action_proposal_service,
                action_executor=action_executor,
                commerce_client=commerce_client,
            )
            action_reconciler = ActionReconciler(
                commerce_client=commerce_client,
                transition_service=action_transition_service,
            )
            knowledge_service = KnowledgeService(
                database.session_factory,
                repository=KnowledgeRepository(),
            )
            gate_scorer: EvidenceGateScorer | None = None
            gate_threshold = None
            if evaluation_profile is not None and evaluation_profile.evidence_gate is not None:
                gate_threshold = evaluation_profile.evidence_gate_threshold
                if evaluation_profile.evidence_gate is EvidenceGate.G0_CURRENT_RRF:
                    gate_scorer = RrfTopScoreGateScorer()
                elif evaluation_profile.evidence_gate is EvidenceGate.G1_DENSE_SIMILARITY:
                    gate_scorer = DenseSimilarityGateScorer(database.session_factory)
                elif evaluation_profile.evidence_gate is EvidenceGate.G2_TOP_EVIDENCE_CROSS_ENCODER:
                    if reranker_client is None:
                        raise RuntimeError("M5D cross-encoder candidate is unavailable")
                    gate_scorer = TopEvidenceCrossEncoderGateScorer(reranker_client)
            retrieval_service = RetrievalService(
                database.session_factory,
                embedding_client=embedding_client,
                reranker_client=reranker_client,
                profile=PRODUCTION_RETRIEVAL_PROFILE,
                evidence_gate_scorer=gate_scorer,
                evidence_gate_threshold=gate_threshold,
            )
            agent_runtime = AgentRuntime(
                conversation_service=conversation_service,
                llm_client=llm_client,
                commerce_client=commerce_client,
                action_proposal_service=action_proposal_service,
                retrieval_service=retrieval_service,
                citation_finalizer=CitationFinalizer(),
                evaluation_profile=evaluation_profile,
                p4_trace_store=(
                    P4TraceStore(
                        dependencies.p4_trace_run_directory,
                        dependencies.p4_trace_run_id,
                        secrets_to_hide=(
                            dependencies.settings.llm.api_key.get_secret_value(),
                            dependencies.settings.commerce.service_token.get_secret_value(),
                            dependencies.settings.auth.development_token.get_secret_value(),
                        ),
                    )
                    if evaluation_profile is not None
                    and evaluation_profile.grounding_candidate
                    is GroundingCandidate.P4_EVIDENCE_LINKED_SINGLE_PASS
                    and dependencies.p4_trace_run_directory is not None
                    and dependencies.p4_trace_run_id is not None
                    else None
                ),
                p5_trace_store=(
                    P5TraceStore(
                        dependencies.p5_trace_run_directory,
                        dependencies.p5_trace_run_id,
                        secrets_to_hide=(
                            dependencies.settings.llm.api_key.get_secret_value(),
                            dependencies.settings.commerce.service_token.get_secret_value(),
                            dependencies.settings.auth.development_token.get_secret_value(),
                        ),
                    )
                    if evaluation_profile is not None
                    and evaluation_profile.grounding_candidate
                    is GroundingCandidate.P5_PROMPT_JSON_EXTRACTIVE_SINGLE_PASS
                    and dependencies.p5_trace_run_directory is not None
                    and dependencies.p5_trace_run_id is not None
                    else None
                ),
            )
        app.state.verbaops_runtime_resources = RuntimeResources(
            database=database,
            redis=redis,
            llm_http_client=llm_http_client,
            commerce_http_client=commerce_http_client,
            rag_http_client=rag_http_client,
            llm_client=llm_client,
            commerce_client=commerce_client,
            conversation_service=conversation_service,
            action_proposal_service=action_proposal_service,
            action_executor=action_executor,
            action_decision_service=action_decision_service,
            action_reconciler=action_reconciler,
            agent_runtime=agent_runtime,
            embedding_client=embedding_client,
            knowledge_service=knowledge_service,
            reranker_client=reranker_client,
            retrieval_service=retrieval_service,
            voice_session_service=voice_session_service,
            voice_token_issuer=voice_token_issuer,
        )
        yield
    finally:
        app.state.verbaops_runtime_resources = None
        try:
            if commerce_http_client is not None:
                await commerce_http_client.aclose()
        finally:
            try:
                try:
                    if rag_http_client is not None:
                        await rag_http_client.aclose()
                finally:
                    if llm_http_client is not None:
                        await llm_http_client.aclose()
            finally:
                try:
                    if redis is not None:
                        await close_redis(redis)
                finally:
                    if database is not None:
                        await dispose_database_resources(database)
