"""Direct LangGraph topology for the bounded read-only text agent."""

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from verbaops.agent.context import AgentContext
from verbaops.agent.errors import AgentProtocolError, AgentUnavailableError
from verbaops.agent.prompts import load_system_prompt
from verbaops.agent.state import AgentState
from verbaops.agent.versions import (
    GRAPH_RECURSION_LIMIT,
    MAX_VISIBLE_HISTORY,
)
from verbaops.llm.errors import LLMError
from verbaops.llm.models import (
    CapabilityAlias,
    ChatMessage,
    GenerateRequest,
    ResponseMetadata,
)
from verbaops.llm.models import (
    ToolDefinition as LLMToolDefinition,
)


def build_agent_graph() -> Any:
    """Compile the fixed M3D graph without checkpoint or tool-node shortcuts."""

    graph = StateGraph(AgentState, context_schema=AgentContext)
    graph.add_node("agent", model_node)
    graph.add_node("validate_tool_calls", validate_tool_calls)
    graph.add_node("execute_tools", execute_tools)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        route_after_agent,
        {"validate_tool_calls": "validate_tool_calls", "finalize": "finalize"},
    )
    graph.add_edge("validate_tool_calls", "execute_tools")
    graph.add_edge("execute_tools", "agent")
    graph.add_edge("finalize", END)
    return graph.compile()


async def model_node(state: AgentState, runtime: Runtime[AgentContext]) -> dict[str, object]:
    """Ask the gateway for one bounded response and persist its metadata."""

    context = _context(runtime)
    request = GenerateRequest(
        capability=CapabilityAlias.AGENT_FAST,
        messages=tuple(_request_messages(state["messages"])),
        tools=tuple(_tool_schemas(context)),
        tool_choice="auto",
    )
    try:
        response = await context.llm_client.generate(request)
    except LLMError:
        await _persist_failed_model_call(context, "llm_unavailable")
        raise AgentUnavailableError() from None
    except Exception:
        await _persist_failed_model_call(context, "llm_unavailable")
        raise AgentUnavailableError() from None

    try:
        await context.conversation_service.append_model_call(
            context.scope,
            context.conversation_id,
            context.agent_run_id,
            response.metadata,
            status="succeeded",
        )
    except Exception:
        raise AgentUnavailableError() from None

    content = response.content
    if not response.tool_calls and (content is None or not content.strip()):
        raise AgentProtocolError()

    assistant_message = ChatMessage(
        role="assistant",
        content=content,
        tool_calls=response.tool_calls or None,
    )
    return {
        "messages": [*state["messages"], assistant_message],
        "pending_tool_calls": list(response.tool_calls),
        "last_tool_results": [],
        "model_call_count": state["model_call_count"] + 1,
        "final_response": content if not response.tool_calls else None,
        "failure": None,
    }


async def validate_tool_calls(
    state: AgentState, runtime: Runtime[AgentContext]
) -> dict[str, object]:
    """Topology placeholder for the explicit validation node."""

    del runtime
    return {"pending_tool_calls": state["pending_tool_calls"]}


async def execute_tools(state: AgentState, runtime: Runtime[AgentContext]) -> dict[str, object]:
    """Topology placeholder for the explicit execution node."""

    del runtime
    return {"pending_tool_calls": state["pending_tool_calls"]}


async def finalize(state: AgentState, runtime: Runtime[AgentContext]) -> dict[str, object]:
    """Finish the graph with the model's already validated final response."""

    del runtime
    return {"final_response": state["final_response"]}


def route_after_agent(state: AgentState) -> str:
    """Route only between explicit validation and finalization nodes."""

    if state["pending_tool_calls"]:
        return "validate_tool_calls"
    return "finalize"


def _context(runtime: Runtime[AgentContext]) -> AgentContext:
    context = runtime.context
    if not isinstance(context, AgentContext):
        raise AgentProtocolError()
    return context


def _request_messages(messages: list[ChatMessage]) -> list[ChatMessage]:
    visible = [message for message in messages if message.role in ("user", "assistant")]
    bounded_visible = visible[-MAX_VISIBLE_HISTORY:]
    tool_messages = [message for message in messages if message.role == "tool"]
    return [
        ChatMessage(role="system", content=load_system_prompt()),
        *bounded_visible,
        *tool_messages,
    ]


def _tool_schemas(context: AgentContext) -> list[LLMToolDefinition]:
    return [
        LLMToolDefinition(
            name=definition.name,
            description=definition.description,
            parameters=definition.input_model.model_json_schema(),
        )
        for definition in context.tool_registry
    ]


async def _persist_failed_model_call(context: AgentContext, error_code: str) -> None:
    metadata = ResponseMetadata(capability_alias=CapabilityAlias.AGENT_FAST)
    try:
        await context.conversation_service.append_model_call(
            context.scope,
            context.conversation_id,
            context.agent_run_id,
            metadata,
            status="failed",
            error_code=error_code,
        )
    except Exception:
        return


__all__ = [
    "GRAPH_RECURSION_LIMIT",
    "build_agent_graph",
    "execute_tools",
    "finalize",
    "model_node",
    "route_after_agent",
    "validate_tool_calls",
]
