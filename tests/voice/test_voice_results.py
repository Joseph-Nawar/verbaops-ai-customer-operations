"""Provider-free tests for structured voice result classification."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest

from verbaops.actions.models import ActionRequestSummary, ActionState, ActionType
from verbaops.agent.runtime import AgentTurnResult
from verbaops.conversations.domain import AgentRunRecord, InteractionMode, MessageRecord
from verbaops.voice.models import VoiceTurnOutcome
from verbaops.voice.results import _outcome, to_voice_turn_result


def _result(*actors: str) -> AgentTurnResult:
    now = datetime.now(UTC)
    conversation_id = uuid4()
    session_id = uuid4()
    turn_id = uuid4()
    user = MessageRecord(uuid4(), conversation_id, 1, "user", "hello", now)
    assistant = MessageRecord(uuid4(), conversation_id, 2, "assistant", "answer", now)
    run = AgentRunRecord(
        uuid4(),
        conversation_id,
        user.id,
        assistant.id,
        "completed",
        "graph",
        "prompt",
        "tools",
        now,
        now,
        None,
        InteractionMode.VOICE,
        session_id,
        turn_id,
    )
    summaries = tuple(
        ActionRequestSummary(
            action_request_id=uuid4(),
            action_type=ActionType.CANCEL_ORDER,
            state=ActionState.AWAITING_CONFIRMATION,
            proposal_fingerprint=f"{index:064x}",
            safe_summary="safe summary",
            required_next_actor=actor,  # type: ignore[arg-type]
            reason_code="allowed",
        )
        for index, actor in enumerate(actors, start=1)
    )
    return AgentTurnResult(
        conversation_id=conversation_id,
        agent_run_id=run.id,
        assistant_message_id=assistant.id,
        content=assistant.content,
        agent_run=run,
        user_message=user,
        assistant_message=assistant,
        action_requests=summaries,
    )


@pytest.mark.parametrize(
    ("actors", "outcome"),
    [
        ((), VoiceTurnOutcome.NORMAL_ANSWER),
        (("customer",), VoiceTurnOutcome.ACTION_PENDING),
        (("support_supervisor",), VoiceTurnOutcome.AWAITING_APPROVAL),
        (("none",), VoiceTurnOutcome.ACTION_RESULT),
        (("customer", "support_supervisor"), VoiceTurnOutcome.AWAITING_APPROVAL),
    ],
)
def test_voice_result_classification_is_structured_and_server_owned(
    actors: tuple[str, ...], outcome: VoiceTurnOutcome
) -> None:
    result = _result(*actors)
    assert result.agent_run.voice_session_id is not None
    assert result.agent_run.voice_turn_id is not None

    projected = to_voice_turn_result(
        result,
        voice_session_id=result.agent_run.voice_session_id,
        voice_turn_id=result.agent_run.voice_turn_id,
    )

    assert projected.outcome is outcome
    assert projected.assistant_text == "answer"
    assert projected.action_prompt is None


def test_unrecognized_action_actor_falls_back_to_normal_answer() -> None:
    result = _result()
    unknown_action = cast(Any, SimpleNamespace(required_next_actor="unknown"))
    result = replace(result, action_requests=(unknown_action,))

    assert _outcome(result) is VoiceTurnOutcome.NORMAL_ANSWER
