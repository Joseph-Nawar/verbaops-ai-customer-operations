"""Narrow provider and transport protocols for the fakeable voice worker."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from verbaops.voice.models import VoiceFinalTranscriptRequest, VoiceTurnResult


class PlayoutHandle(Protocol):
    @property
    def first_audio_at(self) -> datetime | None: ...

    async def wait_complete(self) -> None: ...

    async def cancel(self) -> None: ...


class TTSAdapter(Protocol):
    async def speak(self, text: str) -> PlayoutHandle: ...


class VoiceTranscriptClient(Protocol):
    async def submit_final(
        self, voice_session_id: UUID, request: VoiceFinalTranscriptRequest
    ) -> VoiceTurnResult: ...
