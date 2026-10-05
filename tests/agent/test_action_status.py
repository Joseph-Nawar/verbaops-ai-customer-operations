"""M6F.1 RED tests for server-owned action status in agent turns."""

from dataclasses import replace
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from pydantic import BaseModel

from tests.agent.test_tool_loop import (
    RecordingConversationService,
    make_context,
    make_state,
)
from tests.support.fake_llm import ScriptedLLMClient
from verbaops.actions.models import ActionRequestSummary, ActionState, ActionType
from verbaops.agent.graph import build_agent_graph
from verbaops.llm.models import ToolCall
from verbaops.tools.models import RetryPolicy, RiskLevel, ToolDefinition
from verbaops.tools.registry import ToolRegistry
from verbaops.tools.stage6_models import Stage6RiskLevel


class ProposalInput(BaseModel):
    value: str


def summary(*, state: ActionState = ActionState.AWAITING_CONFIRMATION) -> ActionRequestSummary:
    return ActionRequestSummary(
        action_request_id=uuid4(),
        action_type=ActionType.CANCEL_ORDER,
        state=state,
        proposal_fingerprint="a" * 64,
        safe_summary="Cancel order request is awaiting customer confirmation.",
        required_next_actor="customer",
        reason_code="allowed",
    )


def proposal_registry(result: object) -> ToolRegistry:
    async def handler(_input: ProposalInput, _context: Any, _client: Any) -> object:
        return result

    definition = ToolDefinition(
        name="propose_cancel_order",
        description="Create a pending cancellation proposal.",
        input_model=ProposalInput,
        output_model=ActionRequestSummary,
        risk_level=cast(RiskLevel, Stage6RiskLevel.PROPOSAL),
        timeout_seconds=10.0,
        retry_policy=RetryPolicy(
            max_attempts=1,
            retryable_status_codes=(),
            retry_on_timeout=False,
            retry_on_transport=False,
        ),
        handler=handler,
    )
    return ToolRegistry((definition,))


@pytest.mark.asyncio
async def test_successful_proposal_captures_exact_server_summary() -> None:
    action = summary()
    llm = ScriptedLLMClient(
        [
            make_response(
                None,
                ToolCall(id="proposal-1", name="propose_cancel_order", arguments={"value": "ok"}),
            ),
            make_response("The request is awaiting confirmation."),
        ]
    )
    service = RecordingConversationService()
    context = replace(
        make_context(llm, service, lambda _request: httpx.Response(500)),
        tool_registry=proposal_registry(action),
    )

    result = await build_agent_graph().ainvoke(make_state(), context=context)

    assert result["action_requests"] == [action]
    assert result["final_response"] == "The request is awaiting confirmation."


@pytest.mark.asyncio
async def test_read_only_tool_does_not_create_structured_action_status() -> None:
    llm = ScriptedLLMClient([make_response("The order is in transit.")])
    service = RecordingConversationService()
    context = make_context(llm, service, lambda _request: httpx.Response(500))

    result = await build_agent_graph().ainvoke(make_state(), context=context)

    assert result["action_requests"] == []


@pytest.mark.asyncio
async def test_failed_proposal_does_not_fabricate_action_status() -> None:
    llm = ScriptedLLMClient(
        [
            make_response(
                None,
                ToolCall(id="proposal-1", name="propose_cancel_order", arguments={"bad": "input"}),
            ),
            make_response("I could not create a request."),
        ]
    )
    service = RecordingConversationService()
    context = replace(
        make_context(llm, service, lambda _request: httpx.Response(500)),
        tool_registry=proposal_registry(summary()),
    )

    result = await build_agent_graph().ainvoke(make_state(), context=context)

    assert result["action_requests"] == []


@pytest.mark.asyncio
async def test_model_prose_cannot_override_durable_structured_status() -> None:
    action = summary()
    llm = ScriptedLLMClient(
        [
            make_response(
                None,
                ToolCall(id="proposal-1", name="propose_cancel_order", arguments={"value": "ok"}),
            ),
            make_response("The order was cancelled successfully."),
        ]
    )
    service = RecordingConversationService()
    context = replace(
        make_context(llm, service, lambda _request: httpx.Response(500)),
        tool_registry=proposal_registry(action),
    )

    result = await build_agent_graph().ainvoke(make_state(), context=context)

    assert result["action_requests"][0].state is ActionState.AWAITING_CONFIRMATION
    assert result["action_requests"][0].state is not ActionState.SUCCEEDED


def make_response(content: str | None, *calls: ToolCall):
    return make_response_impl(content, *calls)


def make_response_impl(content: str | None, *calls: ToolCall):
    from verbaops.llm.models import CapabilityAlias, GenerateResponse, ResponseMetadata

    return GenerateResponse(
        content=content,
        tool_calls=calls,
        metadata=ResponseMetadata(capability_alias=CapabilityAlias.AGENT_FAST),
    )
