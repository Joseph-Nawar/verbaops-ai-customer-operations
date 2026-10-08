"""RED-first tests for provider-neutral STT event normalization."""

from uuid import uuid4

import pytest

from verbaops.voice.speech import (
    SpeechEvent,
    SpeechEventKind,
    SpeechEventNormalizer,
    SpeechEventValidationError,
)


def test_partial_event_is_ephemeral_and_never_submitted() -> None:
    normalizer = SpeechEventNormalizer()
    event = normalizer.normalize(SpeechEvent(SpeechEventKind.PARTIAL, "where is", None))

    assert event is not None
    assert event.kind is SpeechEventKind.PARTIAL
    assert event.transcript == "where is"
    assert normalizer.partial_transcript == "where is"
    assert normalizer.submitted_turn_ids == frozenset()


def test_final_event_is_bounded_and_has_stable_turn_id() -> None:
    normalizer = SpeechEventNormalizer()
    voice_turn_id = uuid4()

    event = normalizer.normalize(
        SpeechEvent(SpeechEventKind.FINAL, "  Where is my order?  ", voice_turn_id)
    )

    assert event == SpeechEvent(SpeechEventKind.FINAL, "Where is my order?", voice_turn_id)
    assert normalizer.submitted_turn_ids == frozenset({voice_turn_id})


def test_repeated_final_event_is_deduplicated_at_worker_boundary() -> None:
    normalizer = SpeechEventNormalizer()
    voice_turn_id = uuid4()
    first = normalizer.normalize(SpeechEvent(SpeechEventKind.FINAL, "hello", voice_turn_id))
    second = normalizer.normalize(SpeechEvent(SpeechEventKind.FINAL, "hello", voice_turn_id))

    assert first is not None
    assert second is None
    assert normalizer.submitted_turn_ids == frozenset({voice_turn_id})


@pytest.mark.parametrize(
    "event",
    [
        SpeechEvent(SpeechEventKind.FINAL, "", uuid4()),
        SpeechEvent(SpeechEventKind.FINAL, "   ", uuid4()),
        SpeechEvent(SpeechEventKind.FINAL, "hello", None),
        SpeechEvent(SpeechEventKind.FINAL, "x" * 4001, uuid4()),
    ],
)
def test_invalid_final_event_is_rejected_without_submission(event: SpeechEvent) -> None:
    normalizer = SpeechEventNormalizer()

    with pytest.raises(SpeechEventValidationError):
        normalizer.normalize(event)

    assert normalizer.submitted_turn_ids == frozenset()
