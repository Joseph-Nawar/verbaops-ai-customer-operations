"""Provider-free lifecycle and delegated-authority contracts."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from verbaops.auth.context import Role
from verbaops.voice.domain import VoiceSessionRecord, VoiceSessionState
from verbaops.voice.errors import VoiceSessionLifecycleError, VoiceSessionNotFoundError
from verbaops.voice.service import (
    VoiceSessionService,
    delegated_customer_context,
    session_is_valid,
)


def _record(
    *,
    status: VoiceSessionState = VoiceSessionState.CREATED,
    created_at: datetime | None = None,
) -> VoiceSessionRecord:
    return VoiceSessionRecord(
        id=uuid4(),
        tenant_id=uuid4(),
        principal_id=uuid4(),
        customer_id=uuid4(),
        conversation_id=uuid4(),
        transport_provider="livekit",
        stt_provider="stt",
        tts_provider="tts",
        room_identity="opaque-room",
        participant_identity="opaque-participant",
        status=status,
        created_at=created_at or datetime.now(UTC),
        connected_at=(datetime.now(UTC) if status is VoiceSessionState.CONNECTED else None),
        ended_at=(datetime.now(UTC) if status is VoiceSessionState.ENDED else None),
        error_code=None,
    )


def test_delegated_context_preserves_identity_but_narrows_all_roles_to_customer() -> None:
    record = _record()

    context = delegated_customer_context(record)

    assert context.tenant_id == record.tenant_id
    assert context.principal_id == record.principal_id
    assert context.customer_id == record.customer_id
    assert context.roles == frozenset({Role.CUSTOMER})


@pytest.mark.parametrize(
    ("current", "next_state"),
    [
        (VoiceSessionState.CREATED, VoiceSessionState.CONNECTING),
        (VoiceSessionState.CONNECTING, VoiceSessionState.CONNECTED),
        (VoiceSessionState.CONNECTED, VoiceSessionState.ENDED),
        (VoiceSessionState.CREATED, VoiceSessionState.ENDED),
        (VoiceSessionState.CONNECTING, VoiceSessionState.ENDED),
    ],
)
def test_lifecycle_transition_policy_allows_only_bounded_paths(
    current: VoiceSessionState,
    next_state: VoiceSessionState,
) -> None:
    assert VoiceSessionService.transition_allowed(current, next_state)


@pytest.mark.parametrize(
    ("current", "next_state"),
    [
        (VoiceSessionState.ENDED, VoiceSessionState.CREATED),
        (VoiceSessionState.ENDED, VoiceSessionState.CONNECTING),
        (VoiceSessionState.ENDED, VoiceSessionState.CONNECTED),
        (VoiceSessionState.CREATED, VoiceSessionState.CONNECTED),
        (VoiceSessionState.CONNECTED, VoiceSessionState.CONNECTING),
    ],
)
def test_lifecycle_transition_policy_rejects_reopen_or_skipping_states(
    current: VoiceSessionState,
    next_state: VoiceSessionState,
) -> None:
    assert not VoiceSessionService.transition_allowed(current, next_state)


def test_validity_rejects_ended_and_expired_sessions() -> None:
    now = datetime.now(UTC)
    assert session_is_valid(_record(created_at=now), now=now, ttl=timedelta(minutes=30))
    assert not session_is_valid(
        _record(status=VoiceSessionState.ENDED, created_at=now),
        now=now,
        ttl=timedelta(minutes=30),
    )
    assert not session_is_valid(
        _record(created_at=now - timedelta(minutes=31)),
        now=now,
        ttl=timedelta(minutes=30),
    )


def test_lifecycle_errors_are_non_enumerating_domain_errors() -> None:
    assert issubclass(VoiceSessionNotFoundError, Exception)
    assert issubclass(VoiceSessionLifecycleError, Exception)
