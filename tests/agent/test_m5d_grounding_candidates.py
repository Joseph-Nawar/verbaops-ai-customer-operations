from dataclasses import replace
from typing import Any, cast
from uuid import uuid4

import pytest

from tests.agent.test_retrieval_graph import (
    RecordingRetrieval,
    context,
    evidence,
    response,
    state,
)
from tests.support.fake_llm import ScriptedLLMClient
from verbaops.agent.evaluation import AgentEvaluationProfile, GroundingCandidate
from verbaops.agent.graph import build_agent_graph
from verbaops.retrieval.models import RetrievalResult, RetrievalStatus


def _retrieval() -> RecordingRetrieval:
    return RecordingRetrieval(
        RetrievalResult(
            invocation_id=uuid4(),
            status=RetrievalStatus.SUCCEEDED,
            evidence=(evidence(),),
        )
    )


def _context(llm: ScriptedLLMClient, candidate: GroundingCandidate) -> Any:
    original = context(llm, _retrieval())
    return replace(
        original,
        evaluation_profile=AgentEvaluationProfile(grounding_candidate=candidate),
    )


@pytest.mark.asyncio
async def test_p1_uses_v3_prompt_and_keeps_exact_commerce_tools() -> None:
    llm = ScriptedLLMClient([response("I cannot verify that.")])

    result = cast(
        dict[str, Any],
        await build_agent_graph().ainvoke(
            state("What is the return window?"),
            context=_context(llm, GroundingCandidate.P1_PROMPT_V3),
        ),
    )

    assert result["final_response"] == "I cannot verify that."
    prompt = llm.requests[0].messages[0].content
    assert prompt is not None
    assert "Every company knowledge claim" in prompt
    assert [tool.name for tool in llm.requests[0].tools or ()] == [
        "get_order_status",
        "get_shipment_status",
        "get_refund_status",
        "search_products",
        "list_delivery_slots",
    ]


@pytest.mark.asyncio
async def test_p2_fails_closed_for_accepted_evidence_with_no_citation() -> None:
    llm = ScriptedLLMClient([response("Return within 30 days.")])

    result = cast(
        dict[str, Any],
        await build_agent_graph().ainvoke(
            state("What is the return window?"),
            context=_context(llm, GroundingCandidate.P2_FAIL_CLOSED_CITATIONS),
        ),
    )

    assert result["final_response"] == (
        "I'm unable to verify that information from the available company knowledge."
    )


@pytest.mark.asyncio
async def test_p2_does_not_rewrite_a_turn_that_used_a_commerce_tool() -> None:
    llm = ScriptedLLMClient([response("Your shipment is on the way.")])
    turn_state = state("Where is my order?")
    turn_state["tool_call_count"] = 1

    result = cast(
        dict[str, Any],
        await build_agent_graph().ainvoke(
            turn_state,
            context=_context(llm, GroundingCandidate.P2_FAIL_CLOSED_CITATIONS),
        ),
    )

    assert result["final_response"] == "Your shipment is on the way."


@pytest.mark.asyncio
async def test_p3_makes_one_tool_free_repair_and_accepts_valid_citation() -> None:
    llm = ScriptedLLMClient(
        [response("Return within 30 days."), response("Return within 30 days [[K1]].")]
    )

    result = cast(
        dict[str, Any],
        await build_agent_graph().ainvoke(
            state("What is the return window?"),
            context=_context(llm, GroundingCandidate.P3_ONE_REPAIR_THEN_FAIL_CLOSED),
        ),
    )

    assert result["final_response"] == "Return within 30 days [1]."
    assert result["model_call_count"] == 2
    assert len(llm.requests) == 2
    assert llm.requests[1].tools == ()
    assert llm.requests[1].tool_choice == "none"
    repair_prompt = llm.requests[1].messages[0].content
    assert repair_prompt is not None
    assert "may only add valid supplied citation handles" in repair_prompt


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "repair",
    [
        "Return within 30 days.",
        "The policy allows 30 days [[K1]].",
        "Return within 30 days [[K9]].",
    ],
)
async def test_p3_falls_back_for_missing_new_or_invalid_citation(repair: str) -> None:
    llm = ScriptedLLMClient([response("Return within 30 days."), response(repair)])

    result = cast(
        dict[str, Any],
        await build_agent_graph().ainvoke(
            state("What is the return window?"),
            context=_context(llm, GroundingCandidate.P3_ONE_REPAIR_THEN_FAIL_CLOSED),
        ),
    )

    assert result["final_response"] == (
        "I'm unable to verify that information from the available company knowledge."
    )
    assert result["model_call_count"] == 2
    assert len(llm.requests) == 2
