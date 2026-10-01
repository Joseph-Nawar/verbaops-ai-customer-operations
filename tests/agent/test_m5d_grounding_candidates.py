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


def _retrieval(*, include_evidence: bool = True) -> RecordingRetrieval:
    return RecordingRetrieval(
        RetrievalResult(
            invocation_id=uuid4(),
            status=RetrievalStatus.SUCCEEDED,
            evidence=(evidence(),) if include_evidence else (),
        )
    )


def _context(
    llm: ScriptedLLMClient,
    candidate: GroundingCandidate,
    *,
    include_evidence: bool = True,
) -> Any:
    original = context(llm, _retrieval(include_evidence=include_evidence))
    return replace(
        original,
        evaluation_profile=AgentEvaluationProfile(grounding_candidate=candidate),
    )


def test_p4_profile_pins_its_prompt_graph_and_finalizer_versions() -> None:
    profile = AgentEvaluationProfile(
        grounding_candidate=GroundingCandidate.P4_EVIDENCE_LINKED_SINGLE_PASS
    )

    assert profile.prompt_version == "p4-evidence-linked-v1"
    assert profile.graph_version == "text-agent-m5d-v1"
    assert profile.grounding_finalizer_version == "evidence-linked-extractive-single-pass-v1"


def test_p4_profile_does_not_change_production_or_historical_prompt_versions() -> None:
    assert AgentEvaluationProfile().prompt_version == "v2"
    assert AgentEvaluationProfile().graph_version == "text-agent-m5d-v1"
    assert (
        AgentEvaluationProfile(
            grounding_candidate=GroundingCandidate.P2_FAIL_CLOSED_CITATIONS
        ).prompt_version
        == "v3"
    )


@pytest.mark.asyncio
async def test_p4_knowledge_request_keeps_tools_and_adds_frozen_schema() -> None:
    llm = ScriptedLLMClient([response("{}")])

    await build_agent_graph().ainvoke(
        state("What is the return window?"),
        context=_context(llm, GroundingCandidate.P4_EVIDENCE_LINKED_SINGLE_PASS),
    )

    request = llm.requests[0]
    assert request.response_format is not None
    assert request.response_format["type"] == "json_schema"
    assert request.tool_choice == "auto"
    assert [tool.name for tool in request.tools or ()] == [
        "get_order_status",
        "get_shipment_status",
        "get_refund_status",
        "search_products",
        "list_delivery_slots",
    ]


@pytest.mark.asyncio
async def test_p4_request_without_selected_evidence_uses_plain_path() -> None:
    llm = ScriptedLLMClient([response("I cannot verify that.")])

    result = await build_agent_graph().ainvoke(
        state("What is the return window?"),
        context=_context(
            llm,
            GroundingCandidate.P4_EVIDENCE_LINKED_SINGLE_PASS,
            include_evidence=False,
        ),
    )

    assert llm.requests[0].response_format is None
    assert llm.requests[0].tool_choice == "auto"
    assert len(llm.requests[0].tools or ()) == 5
    assert result["p4_diagnostics"]["p4_extractive_mode_active"] is False
    assert result["p4_diagnostics"]["p4_extractive_mode_reason"] == (
        "no_selected_knowledge_evidence"
    )
    assert result["p4_diagnostics"]["tool_path_entered"] is False


@pytest.mark.asyncio
async def test_blank_p4_knowledge_content_reaches_terminal_finalizer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import verbaops.agent.graph as graph_module

    seen_terminal_content: list[str | None] = []

    async def capture_terminal_content(
        terminal_state: dict[str, Any], runtime: Any
    ) -> dict[str, Any]:
        del runtime
        seen_terminal_content.append(terminal_state["final_response"])
        return {"final_response": "parsed by terminal finalizer", "grounded_citations": []}

    monkeypatch.setattr(graph_module, "finalize_grounding", capture_terminal_content)
    llm = ScriptedLLMClient([response("")])

    result = await build_agent_graph().ainvoke(
        state("What is the return window?"),
        context=_context(llm, GroundingCandidate.P4_EVIDENCE_LINKED_SINGLE_PASS),
    )

    assert result["final_response"] == "parsed by terminal finalizer"
    assert seen_terminal_content == [""]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "failure_reason"),
    [
        ("{broken", "invalid_json"),
        ('{"claims":[{"claim_text":"x"}]}', "invalid_p4_schema"),
        (None, "missing_or_blank_terminal_content"),
        ("  \n", "missing_or_blank_terminal_content"),
    ],
)
async def test_malformed_p4_terminal_fails_closed_without_an_extra_model_call(
    content: str | None, failure_reason: str
) -> None:
    llm = ScriptedLLMClient([response(content)])

    result = cast(
        dict[str, Any],
        await build_agent_graph().ainvoke(
            state("What is the return window?"),
            context=_context(llm, GroundingCandidate.P4_EVIDENCE_LINKED_SINGLE_PASS),
        ),
    )

    assert result["final_response"] == (
        "I'm unable to verify that information from the available company knowledge."
    )
    assert result["model_call_count"] == 1
    assert len(llm.requests) == 1
    assert result["p4_diagnostics"]["parse_success"] is False
    assert result["p4_diagnostics"]["parse_failure_reason"] == failure_reason
    assert result["p4_diagnostics"]["accepted_claims"] == []
    assert result["p4_diagnostics"]["p4_extractive_mode_active"] is True
    assert result["p4_diagnostics"]["p4_extractive_mode_reason"] == (
        "selected_evidence_no_tool_path"
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
