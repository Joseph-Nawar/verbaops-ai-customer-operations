"""Conversion of durable AgentRuntime results into the voice boundary DTO."""

from uuid import UUID

from verbaops.agent.runtime import AgentTurnResult
from verbaops.voice.models import VoiceTurnOutcome, VoiceTurnResult


def to_voice_turn_result(
    result: AgentTurnResult,
    *,
    voice_session_id: UUID,
    voice_turn_id: UUID,
) -> VoiceTurnResult:
    """Project only server-owned runtime values into the worker response."""

    return VoiceTurnResult(
        voice_session_id=voice_session_id,
        conversation_id=result.conversation_id,
        voice_turn_id=voice_turn_id,
        agent_run_id=result.agent_run_id,
        assistant_message_id=result.assistant_message_id,
        assistant_text=result.content,
        outcome=_outcome(result),
        action_requests=result.action_requests,
        action_prompt=None,
    )


def _outcome(result: AgentTurnResult) -> VoiceTurnOutcome:
    if not result.action_requests:
        return VoiceTurnOutcome.NORMAL_ANSWER
    actors = {summary.required_next_actor for summary in result.action_requests}
    if "support_supervisor" in actors:
        return VoiceTurnOutcome.AWAITING_APPROVAL
    if "customer" in actors:
        return VoiceTurnOutcome.ACTION_PENDING
    if actors == {"none"}:
        return VoiceTurnOutcome.ACTION_RESULT
    return VoiceTurnOutcome.NORMAL_ANSWER
