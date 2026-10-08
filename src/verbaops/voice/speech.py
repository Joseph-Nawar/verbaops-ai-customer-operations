"""Provider-neutral speech event and final-transcript normalization."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

MAX_FINAL_TRANSCRIPT_CHARS = 4000


class SpeechEventKind(StrEnum):
    """The only speech event kinds allowed across the provider boundary."""

    PARTIAL = "partial"
    FINAL = "final"


@dataclass(frozen=True, slots=True)
class SpeechEvent:
    """Normalized speech data without provider payloads or provider identifiers."""

    kind: SpeechEventKind
    transcript: str
    voice_turn_id: UUID | None


class STTAdapter(Protocol):
    """Minimal provider adapter contract consumed by a future worker."""

    def events(self) -> AsyncIterator[SpeechEvent]: ...


class SpeechEventValidationError(ValueError):
    """Raised when a normalized speech event cannot enter the worker boundary."""


class SpeechEventNormalizer:
    """Keep partial display state ephemeral and deduplicate FINAL events locally."""

    def __init__(self) -> None:
        self._partial_transcript = ""
        self._submitted_turn_ids: set[UUID] = set()

    @property
    def partial_transcript(self) -> str:
        """Return the latest ephemeral partial text; it is never durable state."""

        return self._partial_transcript

    @property
    def submitted_turn_ids(self) -> frozenset[UUID]:
        """Return only local FINAL de-duplication keys."""

        return frozenset(self._submitted_turn_ids)

    def normalize(self, event: SpeechEvent) -> SpeechEvent | None:
        """Normalize one event; only a first valid FINAL is eligible downstream."""

        if event.kind is SpeechEventKind.PARTIAL:
            if not isinstance(event.transcript, str):
                raise SpeechEventValidationError("partial transcript is invalid")
            self._partial_transcript = event.transcript
            return event
        if event.kind is not SpeechEventKind.FINAL:
            raise SpeechEventValidationError("speech event kind is invalid")
        transcript = event.transcript.strip() if isinstance(event.transcript, str) else ""
        if not transcript or len(transcript) > MAX_FINAL_TRANSCRIPT_CHARS:
            raise SpeechEventValidationError("final transcript is invalid")
        if event.voice_turn_id is None:
            raise SpeechEventValidationError("final transcript requires a voice turn ID")
        if event.voice_turn_id in self._submitted_turn_ids:
            return None
        self._submitted_turn_ids.add(event.voice_turn_id)
        self._partial_transcript = ""
        return SpeechEvent(SpeechEventKind.FINAL, transcript, event.voice_turn_id)

    def forget_final(self, voice_turn_id: UUID) -> None:
        """Release a local key after transport failure; durable idempotency remains authoritative."""

        self._submitted_turn_ids.discard(voice_turn_id)
