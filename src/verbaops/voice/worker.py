"""Provider-neutral Voice Worker coordination around server-owned boundaries."""

from uuid import UUID

from verbaops.voice.models import VoiceFinalTranscriptRequest, VoiceTurnResult
from verbaops.voice.speech import SpeechEvent, SpeechEventKind, SpeechEventNormalizer
from verbaops.voice.worker_protocols import PlayoutHandle, TTSAdapter, VoiceTranscriptClient


class VoiceWorkerCoordinator:
    """Coordinate normalized speech, internal VerbaOps calls, and TTS playout."""

    def __init__(
        self,
        *,
        voice_session_id: UUID,
        transcript_client: VoiceTranscriptClient,
        tts_adapter: TTSAdapter,
        normalizer: SpeechEventNormalizer | None = None,
    ) -> None:
        self._voice_session_id = voice_session_id
        self._transcript_client = transcript_client
        self._tts_adapter = tts_adapter
        self._normalizer = normalizer or SpeechEventNormalizer()
        self._playout: PlayoutHandle | None = None

    async def handle_speech_event(self, event: SpeechEvent) -> VoiceTurnResult | None:
        """Submit only the first valid FINAL and speak its server-owned response."""

        normalized = self._normalizer.normalize(event)
        if normalized is None or normalized.kind is SpeechEventKind.PARTIAL:
            return None
        assert normalized.voice_turn_id is not None
        request = VoiceFinalTranscriptRequest(
            voice_turn_id=normalized.voice_turn_id,
            transcript=normalized.transcript,
        )
        try:
            result = await self._transcript_client.submit_final(self._voice_session_id, request)
        except Exception:
            self._normalizer.forget_final(normalized.voice_turn_id)
            raise
        try:
            self._playout = await self._tts_adapter.speak(result.assistant_text)
        except Exception:
            self._normalizer.forget_final(normalized.voice_turn_id)
            raise
        return result

    async def handle_playout_completed(self) -> None:
        """Wait for the current playout; completion grants no business authority."""

        if self._playout is None:
            return
        playout = self._playout
        await playout.wait_complete()
        if self._playout is playout:
            self._playout = None

    async def handle_interruption(self) -> None:
        """Cancel current audio without creating a durable business decision."""

        await self._cancel_active_playout()

    async def handle_disconnect(self) -> None:
        """Clean up ephemeral audio state when transport disconnects."""

        await self._cancel_active_playout()

    async def handle_session_ended(self) -> None:
        """Clean up ephemeral audio state after the durable session ends."""

        await self._cancel_active_playout()

    async def handle_provider_error(self) -> None:
        """Clean up ephemeral audio state after a provider-side failure."""

        await self._cancel_active_playout()

    async def _cancel_active_playout(self) -> None:
        if self._playout is None:
            return
        playout = self._playout
        self._playout = None
        await playout.cancel()
