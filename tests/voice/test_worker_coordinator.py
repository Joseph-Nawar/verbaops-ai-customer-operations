"""RED-first tests for the fakeable provider-neutral Voice Worker coordinator."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from verbaops.voice.models import VoiceFinalTranscriptRequest, VoiceTurnOutcome, VoiceTurnResult
from verbaops.voice.speech import SpeechEvent, SpeechEventKind, SpeechEventNormalizer
from verbaops.voice.worker import VoiceWorkerCoordinator


class FakePlayout:
    def __init__(self) -> None:
        self.first_audio_at = datetime.now(UTC)
        self.wait_count = 0
        self.cancel_count = 0

    async def wait_complete(self) -> None:
        self.wait_count += 1

    async def cancel(self) -> None:
        self.cancel_count += 1


class FakeTTS:
    def __init__(self) -> None:
        self.texts: list[str] = []
        self.playouts: list[FakePlayout] = []

    async def speak(self, text: str) -> FakePlayout:
        self.texts.append(text)
        playout = FakePlayout()
        self.playouts.append(playout)
        return playout


class FakeTranscriptClient:
    def __init__(self, result: VoiceTurnResult) -> None:
        self.result = result
        self.requests: list[tuple[UUID, VoiceFinalTranscriptRequest]] = []

    async def submit_final(
        self, voice_session_id: UUID, request: VoiceFinalTranscriptRequest
    ) -> VoiceTurnResult:
        self.requests.append((voice_session_id, request))
        return self.result


class FailingTranscriptClient(FakeTranscriptClient):
    async def submit_final(
        self, voice_session_id: UUID, request: VoiceFinalTranscriptRequest
    ) -> VoiceTurnResult:
        del voice_session_id, request
        raise RuntimeError("transcript transport failed")


class FailingTTS:
    async def speak(self, _text: str) -> FakePlayout:
        raise RuntimeError("tts provider failed")


def _result(session_id: UUID, turn_id: UUID) -> VoiceTurnResult:
    return VoiceTurnResult(
        voice_session_id=session_id,
        conversation_id=uuid4(),
        voice_turn_id=turn_id,
        agent_run_id=uuid4(),
        assistant_message_id=uuid4(),
        assistant_text="server answer",
        outcome=VoiceTurnOutcome.NORMAL_ANSWER,
        action_requests=(),
        action_prompt=None,
    )


@pytest.mark.asyncio
async def test_partial_is_ephemeral_and_final_submits_then_speaks_server_text() -> None:
    session_id = uuid4()
    turn_id = uuid4()
    client = FakeTranscriptClient(_result(session_id, turn_id))
    tts = FakeTTS()
    worker = VoiceWorkerCoordinator(
        voice_session_id=session_id,
        transcript_client=client,
        tts_adapter=tts,
    )

    assert (
        await worker.handle_speech_event(SpeechEvent(SpeechEventKind.PARTIAL, "where", None))
        is None
    )
    result = await worker.handle_speech_event(
        SpeechEvent(SpeechEventKind.FINAL, "  where is my order?  ", turn_id)
    )

    assert result is client.result
    assert len(client.requests) == 1
    assert client.requests[0] == (
        session_id,
        VoiceFinalTranscriptRequest(voice_turn_id=turn_id, transcript="where is my order?"),
    )
    assert tts.texts == ["server answer"]
    assert result.action_prompt is None


@pytest.mark.asyncio
async def test_repeated_final_event_has_one_worker_submission() -> None:
    session_id = uuid4()
    turn_id = uuid4()
    client = FakeTranscriptClient(_result(session_id, turn_id))
    worker = VoiceWorkerCoordinator(
        voice_session_id=session_id,
        transcript_client=client,
        tts_adapter=FakeTTS(),
    )
    event = SpeechEvent(SpeechEventKind.FINAL, "hello", turn_id)

    await worker.handle_speech_event(event)
    assert await worker.handle_speech_event(event) is None

    assert len(client.requests) == 1


@pytest.mark.asyncio
async def test_transcript_failure_releases_local_final_deduplication() -> None:
    session_id = uuid4()
    turn_id = uuid4()
    normalizer = SpeechEventNormalizer()
    worker = VoiceWorkerCoordinator(
        voice_session_id=session_id,
        transcript_client=FailingTranscriptClient(_result(session_id, turn_id)),
        tts_adapter=FakeTTS(),
        normalizer=normalizer,
    )

    with pytest.raises(RuntimeError, match="transcript transport failed"):
        await worker.handle_speech_event(SpeechEvent(SpeechEventKind.FINAL, "hello", turn_id))

    assert normalizer.submitted_turn_ids == frozenset()


@pytest.mark.asyncio
async def test_tts_failure_releases_local_final_deduplication() -> None:
    session_id = uuid4()
    turn_id = uuid4()
    normalizer = SpeechEventNormalizer()
    worker = VoiceWorkerCoordinator(
        voice_session_id=session_id,
        transcript_client=FakeTranscriptClient(_result(session_id, turn_id)),
        tts_adapter=FailingTTS(),
        normalizer=normalizer,
    )

    with pytest.raises(RuntimeError, match="tts provider failed"):
        await worker.handle_speech_event(SpeechEvent(SpeechEventKind.FINAL, "hello", turn_id))

    assert normalizer.submitted_turn_ids == frozenset()


@pytest.mark.asyncio
async def test_playout_completion_and_interruption_have_no_confirmation_authority() -> None:
    session_id = uuid4()
    turn_id = uuid4()
    tts = FakeTTS()
    worker = VoiceWorkerCoordinator(
        voice_session_id=session_id,
        transcript_client=FakeTranscriptClient(_result(session_id, turn_id)),
        tts_adapter=tts,
    )

    await worker.handle_playout_completed()
    await worker.handle_speech_event(SpeechEvent(SpeechEventKind.FINAL, "hello", turn_id))
    await worker.handle_playout_completed()
    assert tts.playouts[0].wait_count == 1
    await worker.handle_interruption()
    assert tts.playouts[0].cancel_count == 0
    assert not hasattr(worker, "arm_confirmation")


@pytest.mark.asyncio
async def test_playout_completion_does_not_clear_replacement_playout() -> None:
    session_id = uuid4()
    turn_id = uuid4()

    class ReplacingPlayout(FakePlayout):
        async def wait_complete(self) -> None:
            await super().wait_complete()
            worker._playout = FakePlayout()

    class ReplacingTTS:
        async def speak(self, _text: str) -> ReplacingPlayout:
            return ReplacingPlayout()

    worker = VoiceWorkerCoordinator(
        voice_session_id=session_id,
        transcript_client=FakeTranscriptClient(_result(session_id, turn_id)),
        tts_adapter=ReplacingTTS(),
    )

    await worker.handle_speech_event(SpeechEvent(SpeechEventKind.FINAL, "hello", turn_id))
    await worker.handle_playout_completed()

    assert worker._playout is not None


@pytest.mark.asyncio
async def test_disconnect_and_session_end_cancel_active_playout() -> None:
    session_id = uuid4()
    turn_id = uuid4()
    tts = FakeTTS()
    worker = VoiceWorkerCoordinator(
        voice_session_id=session_id,
        transcript_client=FakeTranscriptClient(_result(session_id, turn_id)),
        tts_adapter=tts,
    )

    await worker.handle_speech_event(SpeechEvent(SpeechEventKind.FINAL, "hello", turn_id))
    await worker.handle_disconnect()
    assert tts.playouts[0].cancel_count == 1

    next_turn_id = uuid4()
    await worker.handle_speech_event(SpeechEvent(SpeechEventKind.FINAL, "goodbye", next_turn_id))
    await worker.handle_session_ended()
    assert tts.playouts[1].cancel_count == 1
    await worker.handle_provider_error()


@pytest.mark.asyncio
async def test_restart_recreates_ephemeral_worker_without_role_or_action_authority() -> None:
    session_id = uuid4()
    turn_id = uuid4()
    client = FakeTranscriptClient(_result(session_id, turn_id))
    first = VoiceWorkerCoordinator(
        voice_session_id=session_id,
        transcript_client=client,
        tts_adapter=FakeTTS(),
    )
    await first.handle_speech_event(SpeechEvent(SpeechEventKind.FINAL, "hello", turn_id))

    restarted = VoiceWorkerCoordinator(
        voice_session_id=session_id,
        transcript_client=client,
        tts_adapter=FakeTTS(),
    )
    result = await restarted.handle_speech_event(
        SpeechEvent(SpeechEventKind.FINAL, "hello", turn_id)
    )

    assert result is client.result
    assert len(client.requests) == 2
    assert not hasattr(restarted, "trusted_context")
    assert not hasattr(restarted, "action_executor")
