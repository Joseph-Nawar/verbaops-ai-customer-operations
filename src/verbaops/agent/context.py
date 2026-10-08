"""Immutable trusted dependencies for one graph invocation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from verbaops.auth.context import TrustedContext

if TYPE_CHECKING:
    from verbaops.agent.evaluation import AgentEvaluationProfile
    from verbaops.commerce.client import CommerceClient
    from verbaops.conversations.domain import ConversationScope
    from verbaops.conversations.service import ConversationService
    from verbaops.llm.client import LLMClient
    from verbaops.retrieval.grounding import CitationFinalizer
    from verbaops.retrieval.service import RetrievalService
    from verbaops.tools.registry import ToolRegistry


class InteractionMode(StrEnum):
    """Durable provenance for a user interaction entering AgentRuntime."""

    TEXT = "text"
    VOICE = "voice"


@dataclass(frozen=True, slots=True)
class AgentContext:
    """Trusted identity and dependency context excluded from mutable graph state."""

    conversation_id: UUID
    agent_run_id: UUID
    trusted_context: TrustedContext
    llm_client: LLMClient
    commerce_client: CommerceClient
    tool_registry: ToolRegistry
    conversation_service: ConversationService
    retrieval_service: RetrievalService | None = None
    citation_finalizer: CitationFinalizer | None = None
    evaluation_profile: AgentEvaluationProfile | None = None

    @property
    def scope(self) -> ConversationScope:
        """Derive persistence scope from the single authenticated identity value."""

        from verbaops.conversations.domain import ConversationScope

        return ConversationScope(
            tenant_id=self.trusted_context.tenant_id,
            principal_id=self.trusted_context.principal_id,
        )
