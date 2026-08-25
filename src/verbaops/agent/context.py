"""Immutable trusted dependencies for one graph invocation."""

from dataclasses import dataclass
from uuid import UUID

from verbaops.commerce.client import CommerceClient
from verbaops.conversations.domain import ConversationScope
from verbaops.conversations.service import ConversationService
from verbaops.llm.client import LLMClient
from verbaops.tools.registry import ToolRegistry
from verbaops.retrieval.grounding import CitationFinalizer
from verbaops.retrieval.service import RetrievalService


@dataclass(frozen=True, slots=True)
class AgentContext:
    """Trusted identity and dependency context excluded from mutable graph state."""

    conversation_id: UUID
    agent_run_id: UUID
    scope: ConversationScope
    customer_id: UUID
    llm_client: LLMClient
    commerce_client: CommerceClient
    tool_registry: ToolRegistry
    conversation_service: ConversationService
    retrieval_service: RetrievalService | None = None
    citation_finalizer: CitationFinalizer | None = None
