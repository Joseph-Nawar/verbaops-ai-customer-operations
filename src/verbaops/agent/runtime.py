"""High-level persisted turn lifecycle for the bounded read-only graph."""

import asyncio
from dataclasses import dataclass
from typing import Any, Literal, cast
from uuid import UUID

from verbaops.actions.models import ActionRequestSummary
from verbaops.actions.proposals import ActionProposalService
from verbaops.agent.context import AgentContext
from verbaops.agent.errors import (
    AgentBusyError,
    AgentError,
    AgentInputError,
    AgentProtocolError,
    AgentUnavailableError,
)
from verbaops.agent.evaluation import AgentEvaluationProfile, GroundingCandidate
from verbaops.agent.graph import build_agent_graph
from verbaops.agent.stage6_versions import (
    STAGE6_PROMPT_VERSION,
    STAGE6_TOOL_SCHEMA_VERSION,
)
from verbaops.agent.state import AgentState
from verbaops.agent.versions import (
    GRAPH_RECURSION_LIMIT,
    GRAPH_VERSION,
    MAX_USER_CONTENT_CHARS,
    MAX_VISIBLE_HISTORY,
    PROMPT_VERSION,
    TOOL_SCHEMA_VERSION,
)
from verbaops.auth.context import TrustedContext
from verbaops.commerce.client import CommerceClient
from verbaops.conversations.domain import (
    AgentRunRecord,
    ConversationScope,
    MessageRecord,
)
from verbaops.conversations.errors import ConversationBusyError
from verbaops.conversations.service import ConversationService
from verbaops.evaluation.p4_trace import P4TraceStore
from verbaops.evaluation.p5_trace import P5TraceStore
from verbaops.llm.client import LLMClient
from verbaops.llm.models import ChatMessage
from verbaops.retrieval.grounding import CitationFinalizer
from verbaops.retrieval.service import RetrievalService
from verbaops.tools.registry import (
    ToolRegistry,
    build_commerce_read_registry,
)
from verbaops.tools.stage6_registry import build_stage6_tool_registry


@dataclass(frozen=True, slots=True)
class AgentTurnResult:
    """Application-owned result returned after a persisted successful turn."""

    conversation_id: UUID
    agent_run_id: UUID
    assistant_message_id: UUID
    content: str
    agent_run: AgentRunRecord
    user_message: MessageRecord
    assistant_message: MessageRecord
    action_requests: tuple[ActionRequestSummary, ...] = ()


class AgentRuntime:
    """Coordinate short persistence operations around one graph invocation."""

    def __init__(
        self,
        *,
        conversation_service: ConversationService,
        llm_client: LLMClient,
        commerce_client: CommerceClient,
        action_proposal_service: ActionProposalService | None = None,
        tool_registry: ToolRegistry | None = None,
        graph: Any | None = None,
        retrieval_service: RetrievalService | None = None,
        citation_finalizer: CitationFinalizer | None = None,
        evaluation_profile: AgentEvaluationProfile | None = None,
        p4_trace_store: P4TraceStore | None = None,
        p5_trace_store: P5TraceStore | None = None,
        deadline_seconds: float = 45.0,
    ) -> None:
        is_p4 = bool(
            evaluation_profile is not None
            and evaluation_profile.grounding_candidate
            is GroundingCandidate.P4_EVIDENCE_LINKED_SINGLE_PASS
        )
        is_p5 = bool(
            evaluation_profile is not None
            and evaluation_profile.grounding_candidate
            is GroundingCandidate.P5_PROMPT_JSON_EXTRACTIVE_SINGLE_PASS
        )
        if is_p4 != (p4_trace_store is not None):
            raise ValueError("P4 runtime requires an explicitly configured P4 trace store")
        if is_p5 != (p5_trace_store is not None):
            raise ValueError("P5 runtime requires an explicitly configured P5 trace store")
        if (
            evaluation_profile is not None
            and tool_registry is not None
            and any(name.startswith("propose_") for name in tool_registry.names)
        ):
            raise ValueError("evaluation profiles cannot expose Stage 6 proposal tools")
        self._conversation_service = conversation_service
        self._llm_client = llm_client
        self._commerce_client = commerce_client
        if tool_registry is not None:
            self._tool_registry = tool_registry
        elif evaluation_profile is None and action_proposal_service is not None:
            self._tool_registry = build_stage6_tool_registry(action_proposal_service)
        else:
            self._tool_registry = build_commerce_read_registry()
        has_proposal_tools = any(name.startswith("propose_") for name in self._tool_registry.names)
        self._tool_schema_version = (
            STAGE6_TOOL_SCHEMA_VERSION
            if evaluation_profile is None and has_proposal_tools
            else TOOL_SCHEMA_VERSION
        )
        self._prompt_version = (
            STAGE6_PROMPT_VERSION
            if evaluation_profile is None and has_proposal_tools
            else PROMPT_VERSION
        )
        self._graph = graph or build_agent_graph()
        self._retrieval_service = retrieval_service
        self._citation_finalizer = citation_finalizer
        self._evaluation_profile = evaluation_profile
        self._p4_trace_store = p4_trace_store
        self._p5_trace_store = p5_trace_store
        self._deadline_seconds = deadline_seconds

    async def run_turn(
        self,
        trusted_context: TrustedContext,
        conversation_id: UUID,
        content: str,
    ) -> AgentTurnResult:
        """Run one validated turn without holding a transaction over external work."""

        self._validate_content(content)
        scope = ConversationScope(
            tenant_id=trusted_context.tenant_id,
            principal_id=trusted_context.principal_id,
        )
        try:
            turn_start = await self._conversation_service.start_turn(
                scope,
                conversation_id,
                content,
                graph_version=(
                    self._evaluation_profile.graph_version
                    if self._evaluation_profile is not None
                    else GRAPH_VERSION
                ),
                prompt_version=(
                    f"text-agent-system-{self._evaluation_profile.prompt_version}"
                    if self._evaluation_profile is not None
                    else self._prompt_version
                ),
                tool_schema_version=self._tool_schema_version,
            )
        except ConversationBusyError:
            raise AgentBusyError() from None

        try:
            history = await self._conversation_service.list_messages(scope, conversation_id)
            context = AgentContext(
                conversation_id=conversation_id,
                agent_run_id=turn_start.agent_run.id,
                trusted_context=trusted_context,
                llm_client=self._llm_client,
                commerce_client=self._commerce_client,
                tool_registry=self._tool_registry,
                conversation_service=self._conversation_service,
                retrieval_service=self._retrieval_service,
                citation_finalizer=self._citation_finalizer,
                evaluation_profile=self._evaluation_profile,
            )
            final_state = await asyncio.wait_for(
                self._graph.ainvoke(
                    _initial_state(history),
                    context=context,
                    config={"recursion_limit": GRAPH_RECURSION_LIMIT},
                ),
                timeout=self._deadline_seconds,
            )
            final_response = final_state.get("final_response")
            if not isinstance(final_response, str) or not final_response.strip():
                raise AgentProtocolError()
            if self._p4_trace_store is not None:
                diagnostics = final_state.get("p4_diagnostics")
                if not isinstance(diagnostics, dict):
                    raise AgentProtocolError()
                self._p4_trace_store.write(turn_start.agent_run.id, diagnostics)
            if self._p5_trace_store is not None:
                diagnostics = final_state.get("p5_diagnostics")
                if not isinstance(diagnostics, dict):
                    raise AgentProtocolError()
                self._p5_trace_store.write(turn_start.agent_run.id, diagnostics)
            retrieval_invocation_id = final_state.get("retrieval_invocation_id")
            grounded_citations = final_state.get("grounded_citations", [])
            if retrieval_invocation_id is not None or grounded_citations:
                completion = await self._conversation_service.complete_turn(
                    scope,
                    conversation_id,
                    turn_start.agent_run.id,
                    final_response,
                    retrieval_invocation_id=retrieval_invocation_id,
                    citations=grounded_citations,
                )
            else:
                completion = await self._conversation_service.complete_turn(
                    scope,
                    conversation_id,
                    turn_start.agent_run.id,
                    final_response,
                )
            raw_action_requests = final_state.get("action_requests", [])
            if not isinstance(raw_action_requests, (list, tuple)) or not all(
                isinstance(item, ActionRequestSummary) for item in raw_action_requests
            ):
                raise AgentProtocolError()
        except TimeoutError:
            error = AgentUnavailableError()
            await self._fail_run(scope, conversation_id, turn_start.agent_run.id, error)
            raise error from None
        except AgentError as agent_error:
            await self._fail_run(scope, conversation_id, turn_start.agent_run.id, agent_error)
            raise
        except Exception:
            error = AgentUnavailableError()
            await self._fail_run(scope, conversation_id, turn_start.agent_run.id, error)
            raise error from None

        return AgentTurnResult(
            conversation_id=conversation_id,
            agent_run_id=turn_start.agent_run.id,
            assistant_message_id=completion.assistant_message.id,
            content=completion.assistant_message.content,
            agent_run=completion.agent_run,
            user_message=turn_start.user_message,
            assistant_message=completion.assistant_message,
            action_requests=tuple(raw_action_requests),
        )

    @staticmethod
    def _validate_content(content: str) -> None:
        if not isinstance(content, str) or not content.strip():
            raise AgentInputError()
        if len(content) > MAX_USER_CONTENT_CHARS:
            raise AgentInputError()

    async def _fail_run(
        self,
        scope: ConversationScope,
        conversation_id: UUID,
        agent_run_id: UUID,
        error: AgentError,
    ) -> None:
        try:
            await self._conversation_service.fail_turn(
                scope,
                conversation_id,
                agent_run_id,
                error.error_code,
            )
        except Exception:
            return


def _initial_state(history: list[MessageRecord]) -> AgentState:
    visible_history = [record for record in history if record.role in ("user", "assistant")]
    messages = [
        ChatMessage(role=cast(Literal["user", "assistant"], record.role), content=record.content)
        for record in visible_history[-MAX_VISIBLE_HISTORY:]
    ]
    return {
        "messages": messages,
        "pending_tool_calls": [],
        "last_tool_results": [],
        "model_call_count": 0,
        "tool_round_count": 0,
        "tool_call_count": 0,
        "tool_path_entered": False,
        "validation_repair_count": 0,
        "final_response": None,
        "failure": None,
        "knowledge_status": None,
        "knowledge_evidence": [],
        "retrieval_invocation_id": None,
        "grounded_citations": [],
        "action_requests": [],
    }


__all__ = ["AgentRuntime", "AgentTurnResult"]
