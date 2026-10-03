"""Provider-free graph tests for Stage 6 proposal tool execution."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr

from tests.support.fake_llm import ScriptedLLMClient
from verbaops.actions.models import ActionRequestSummary, ActionState
from verbaops.agent.context import AgentContext
from verbaops.agent.evaluation import AgentEvaluationProfile, GroundingCandidate
from verbaops.agent.graph import execute_tools
from verbaops.agent.runtime import AgentRuntime
from verbaops.agent.stage6_versions import (
    STAGE6_PROMPT_VERSION,
    STAGE6_TOOL_SCHEMA_VERSION,
)
from verbaops.agent.state import AgentState
from verbaops.agent.versions import (
    PROMPT_VERSION,
    TOOL_SCHEMA_VERSION,
)
from verbaops.auth.context import Role, TrustedContext
from verbaops.commerce.client import CommerceClient
from verbaops.config import CommerceSettings
from verbaops.conversations.service import ConversationService
from verbaops.evaluation.p4_trace import P4TraceStore
from verbaops.evaluation.p5_trace import P5TraceStore
from verbaops.llm.models import (
    ChatMessage,
    ToolCall,
)
from verbaops.tools.registry import build_commerce_read_registry
from verbaops.tools.stage6_registry import build_stage6_tool_registry


@dataclass
class ProposalServiceSpy:
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def propose(self, **kwargs: Any) -> ActionRequestSummary:
        self.calls.append(kwargs)
        return ActionRequestSummary(
            action_request_id=uuid4(),
            action_type=kwargs["proposal"].action_type,
            state=ActionState.AWAITING_APPROVAL,
            proposal_fingerprint="b" * 64,
            safe_summary="A proposal is waiting for supervisor review.",
            required_next_actor="support_supervisor",
            reason_code="allowed",
        )


class RecordingConversationService:
    def __init__(self) -> None:
        self.invocations: dict[UUID, dict[str, Any]] = {}

    async def begin_tool_invocation(self, *args: Any, **kwargs: Any) -> Any:
        invocation_id = uuid4()
        self.invocations[invocation_id] = {"args": args, "kwargs": kwargs, "status": "proposed"}
        return type("Invocation", (), {"id": invocation_id})()

    async def complete_tool_invocation(
        self, _scope: Any, _conversation_id: UUID, _run_id: UUID, invocation_id: UUID, **kwargs: Any
    ) -> Any:
        self.invocations[invocation_id].update(kwargs)
        return type("Invocation", (), {"id": invocation_id})()


def _state(call: ToolCall) -> AgentState:
    return {
        "messages": [ChatMessage(role="user", content="Please refund my order.")],
        "pending_tool_calls": [call],
        "last_tool_results": [],
        "model_call_count": 0,
        "tool_round_count": 0,
        "tool_call_count": 1,
        "tool_path_entered": False,
        "validation_repair_count": 0,
        "final_response": None,
        "failure": None,
        "knowledge_status": None,
        "knowledge_evidence": [],
        "retrieval_invocation_id": None,
        "grounded_citations": [],
    }


@pytest.mark.asyncio
async def test_graph_passes_persisted_invocation_id_and_returns_server_owned_proposal_state() -> (
    None
):
    order_id = uuid4()
    service = ProposalServiceSpy()
    conversation_service = RecordingConversationService()
    trusted_context = TrustedContext(
        principal_id=uuid4(),
        tenant_id=uuid4(),
        customer_id=uuid4(),
        roles=frozenset({Role.CUSTOMER}),
    )
    commerce = CommerceClient(
        CommerceSettings(base_url="http://commerce.test", service_token=SecretStr("safe")),
        httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _request: (_ for _ in ()).throw(
                    AssertionError("proposal handlers must not perform Commerce HTTP")
                )
            )
        ),
    )
    context = AgentContext(
        conversation_id=uuid4(),
        agent_run_id=uuid4(),
        trusted_context=trusted_context,
        llm_client=cast(ScriptedLLMClient, object()),
        commerce_client=commerce,
        tool_registry=build_stage6_tool_registry(service),
        conversation_service=cast(ConversationService, conversation_service),
    )
    call = ToolCall(
        id="provider-call-17",
        name="propose_refund",
        arguments={"order_id": str(order_id), "amount": "600.00", "reason": "Duplicate charge"},
    )

    result = await execute_tools(_state(call), type("Runtime", (), {"context": context})())

    invocation_id = next(iter(conversation_service.invocations))
    assert service.calls[0]["tool_invocation_id"] == invocation_id
    assert service.calls[0]["tool_invocation_id"] != call.id
    assert conversation_service.invocations[invocation_id]["status"] == "succeeded"
    message = cast(list[ChatMessage], result["last_tool_results"])[0]
    assert message.content is not None
    assert "awaiting_approval" in message.content
    assert "succeeded" not in message.content
    assert message.tool_call_id == call.id
    await commerce._http_client.aclose()


def test_evaluation_read_registry_remains_the_frozen_five_tool_contract() -> None:
    assert build_commerce_read_registry().names == (
        "get_order_status",
        "get_shipment_status",
        "get_refund_status",
        "search_products",
        "list_delivery_slots",
    )


def test_current_runtime_uses_stage6_registry_and_versioned_proposal_prompt() -> None:
    service = ProposalServiceSpy()
    runtime = AgentRuntime(
        conversation_service=cast(ConversationService, object()),
        llm_client=cast(ScriptedLLMClient, object()),
        commerce_client=cast(CommerceClient, object()),
        action_proposal_service=service,  # type: ignore[arg-type]
    )

    assert len(runtime._tool_registry.names) == 10
    assert runtime._tool_schema_version == STAGE6_TOOL_SCHEMA_VERSION
    assert runtime._prompt_version == STAGE6_PROMPT_VERSION


@pytest.mark.parametrize(
    "candidate",
    [
        GroundingCandidate.P4_EVIDENCE_LINKED_SINGLE_PASS,
        GroundingCandidate.P5_PROMPT_JSON_EXTRACTIVE_SINGLE_PASS,
    ],
)
def test_p4_p5_profiles_keep_frozen_read_registry_and_prompt_contract(
    candidate: GroundingCandidate,
    tmp_path: Path,
) -> None:
    service = ProposalServiceSpy()
    run_id = (
        "canonical-M0-P5-m6c-profile-regression"
        if candidate is GroundingCandidate.P5_PROMPT_JSON_EXTRACTIVE_SINGLE_PASS
        else "m6c-p4-profile-regression"
    )
    run_directory = tmp_path / run_id
    p4_trace_store = (
        P4TraceStore(run_directory, run_id)
        if candidate is GroundingCandidate.P4_EVIDENCE_LINKED_SINGLE_PASS
        else None
    )
    p5_trace_store = (
        P5TraceStore(run_directory, run_id)
        if candidate is GroundingCandidate.P5_PROMPT_JSON_EXTRACTIVE_SINGLE_PASS
        else None
    )
    runtime = AgentRuntime(
        conversation_service=cast(ConversationService, object()),
        llm_client=cast(ScriptedLLMClient, object()),
        commerce_client=cast(CommerceClient, object()),
        action_proposal_service=service,  # type: ignore[arg-type]
        evaluation_profile=AgentEvaluationProfile(grounding_candidate=candidate),
        p4_trace_store=p4_trace_store,
        p5_trace_store=p5_trace_store,
    )

    assert runtime._tool_registry.names == build_commerce_read_registry().names
    assert runtime._tool_schema_version == TOOL_SCHEMA_VERSION
    assert runtime._prompt_version == PROMPT_VERSION
    assert runtime._evaluation_profile is not None
    assert runtime._evaluation_profile.prompt_version == "p4-evidence-linked-v1"
