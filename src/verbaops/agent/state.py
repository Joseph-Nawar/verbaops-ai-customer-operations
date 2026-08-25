"""Minimal mutable state passed between LangGraph nodes."""

from typing import TypedDict
from uuid import UUID

from verbaops.agent.errors import AgentError
from verbaops.llm.models import ChatMessage, ToolCall
from verbaops.retrieval.models import RetrievalEvidence


class AgentState(TypedDict):
    """Only transient conversation messages, budgets, and final outcome."""

    messages: list[ChatMessage]
    pending_tool_calls: list[ToolCall]
    last_tool_results: list[ChatMessage]
    model_call_count: int
    tool_round_count: int
    tool_call_count: int
    validation_repair_count: int
    final_response: str | None
    failure: AgentError | None
    knowledge_status: str | None
    knowledge_evidence: list[RetrievalEvidence]
    retrieval_invocation_id: UUID | None
    grounded_citations: list[RetrievalEvidence]
