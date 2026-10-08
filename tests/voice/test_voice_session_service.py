"""Provider-free lifecycle and delegated-authority contracts."""

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest

from verbaops.auth.context import Role
from verbaops.conversations.domain import ConversationRecord
from verbaops.conversations.errors import ConversationNotFoundError
from verbaops.voice.auth import VoiceWorkerContext
from verbaops.voice.domain import VoiceSessionRecord, VoiceSessionState
from verbaops.voice.errors import (
    VoiceSessionAuthorizationError,
    VoiceSessionExpiredError,
    VoiceSessionLifecycleError,
    VoiceSessionNotFoundError,
)
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


class _SessionContext:
    async def __aenter__(self) -> "_SessionContext":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def begin(self) -> "_SessionContext":
        return self


class _SessionFactory:
    def __call__(self) -> _SessionContext:
        return _SessionContext()


def _context(*roles: Role) -> Any:
    from verbaops.auth.context import TrustedContext

    return TrustedContext(
        tenant_id=uuid4(),
        principal_id=uuid4(),
        customer_id=uuid4(),
        roles=frozenset(roles),
    )


def _conversation(context: Any) -> ConversationRecord:
    now = datetime.now(UTC)
    return ConversationRecord(
        id=uuid4(),
        tenant_id=context.tenant_id,
        principal_id=context.principal_id,
        customer_id=context.customer_id,
        created_at=now,
        updated_at=now,
    )


def _service(
    *, conversation_service: Any = None, token_issuer: Any = None, **kwargs: Any
) -> VoiceSessionService:
    return VoiceSessionService(
        cast(Any, _SessionFactory()),
        conversation_service=conversation_service,
        token_issuer=token_issuer,
        **kwargs,
    )


def _repository_mock(record: VoiceSessionRecord) -> Mock:
    repository = Mock()
    repository.create_session = AsyncMock(return_value=record)
    repository.get_customer_session = AsyncMock(return_value=record)
    repository.get_worker_session = AsyncMock(return_value=record)
    repository.update_lifecycle = AsyncMock(return_value=record)
    return repository


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


def test_service_rejects_invalid_ttl_configuration() -> None:
    with pytest.raises(ValueError):
        _service(session_ttl=timedelta(0))
    with pytest.raises(ValueError):
        _service(session_ttl=timedelta(seconds=1), token_ttl=timedelta(seconds=2))


@pytest.mark.asyncio
async def test_bootstrap_requires_customer_authority_and_dependencies() -> None:
    with pytest.raises(VoiceSessionAuthorizationError):
        await _service().create_customer_session(_context(Role.SUPPORT_AGENT), None)

    with pytest.raises(RuntimeError):
        await _service().create_customer_session(_context(Role.CUSTOMER), None)


@pytest.mark.asyncio
async def test_bootstrap_creates_conversation_and_mints_short_lived_token() -> None:
    context = _context(Role.CUSTOMER, Role.SUPPORT_AGENT)
    conversation_service = Mock()
    conversation_service.create_conversation = AsyncMock(return_value=_conversation(context))
    token_issuer = Mock()
    token_issuer.mint_customer_token = AsyncMock(return_value="local-test-token")
    record = _record()
    repository = _repository_mock(record)

    with patch("verbaops.voice.service.VoiceSessionRepository", return_value=repository):
        result = await _service(
            conversation_service=conversation_service,
            token_issuer=token_issuer,
            livekit_url="https://livekit.example.test",
        ).create_customer_session(context, None)

    assert result.voice_session_id == record.id
    assert result.room_token == "local-test-token"
    assert result.status is VoiceSessionState.CREATED
    conversation_service.create_conversation.assert_awaited_once()
    token_issuer.mint_customer_token.assert_awaited_once()


@pytest.mark.asyncio
async def test_bootstrap_existing_conversation_is_scoped_and_foreign_is_hidden() -> None:
    context = _context(Role.CUSTOMER)
    conversation_service = Mock()
    conversation = _conversation(context)
    foreign_conversation = ConversationRecord(
        id=conversation.id,
        tenant_id=conversation.tenant_id,
        principal_id=conversation.principal_id,
        customer_id=uuid4(),
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )
    conversation_service.get_conversation = AsyncMock(
        side_effect=[conversation, foreign_conversation, ConversationNotFoundError()]
    )
    token_issuer = Mock()
    token_issuer.mint_customer_token = AsyncMock(return_value="token")
    repository = _repository_mock(_record())
    service = _service(conversation_service=conversation_service, token_issuer=token_issuer)

    with patch("verbaops.voice.service.VoiceSessionRepository", return_value=repository):
        await service.create_customer_session(context, conversation.id)
        with pytest.raises(VoiceSessionNotFoundError):
            await service.create_customer_session(context, conversation.id)
        conversation_service.get_conversation.side_effect = ConversationNotFoundError()
        with pytest.raises(VoiceSessionNotFoundError):
            await service.create_customer_session(context, conversation.id)


@pytest.mark.asyncio
async def test_token_failure_ends_session_without_persisting_token() -> None:
    context = _context(Role.CUSTOMER)
    conversation_service = Mock()
    conversation_service.create_conversation = AsyncMock(return_value=_conversation(context))
    token_issuer = Mock()
    token_issuer.mint_customer_token = AsyncMock(side_effect=RuntimeError("issuer failure"))
    record = _record()
    repository = _repository_mock(record)

    with (
        patch("verbaops.voice.service.VoiceSessionRepository", return_value=repository),
        pytest.raises(RuntimeError, match="issuer failure"),
    ):
        await _service(
            conversation_service=conversation_service,
            token_issuer=token_issuer,
        ).create_customer_session(context, None)

    repository.update_lifecycle.assert_awaited_once_with(
        record.id,
        status=VoiceSessionState.ENDED,
        ended_at=cast(Any, repository.update_lifecycle.await_args.kwargs["ended_at"]),
        error_code="token_mint_failed",
    )


@pytest.mark.asyncio
async def test_customer_and_worker_reads_apply_authority_and_expiry() -> None:
    context = _context(Role.CUSTOMER)
    repository = _repository_mock(_record())
    service = _service()
    with patch("verbaops.voice.service.VoiceSessionRepository", return_value=repository):
        loaded = await service.get_customer_session(
            repository.get_customer_session.return_value.id, context
        )
        assert loaded.status is VoiceSessionState.CREATED
        worker = await service.get_worker_session(loaded.id, VoiceWorkerContext())
        assert worker.id == loaded.id

    with pytest.raises(VoiceSessionAuthorizationError):
        await service.get_customer_session(loaded.id, _context(Role.SUPPORT_AGENT))
    expired = _record(created_at=datetime.now(UTC) - timedelta(hours=1))
    repository.get_customer_session.return_value = expired
    with (
        patch("verbaops.voice.service.VoiceSessionRepository", return_value=repository),
        pytest.raises(VoiceSessionExpiredError),
    ):
        await service.get_customer_session(expired.id, context)


@pytest.mark.asyncio
async def test_worker_lifecycle_transitions_are_locked_and_end_is_idempotent() -> None:
    context = _context(Role.CUSTOMER)
    record = _record()
    repository = _repository_mock(record)
    service = _service()
    with patch("verbaops.voice.service.VoiceSessionRepository", return_value=repository):
        await service.mark_connecting(record.id)
        repository.get_worker_session.return_value = _record(status=VoiceSessionState.CONNECTING)
        await service.mark_connecting(record.id)
        repository.get_worker_session.return_value = _record(status=VoiceSessionState.CONNECTING)
        await service.mark_connected(record.id)
        repository.get_worker_session.return_value = _record(status=VoiceSessionState.CONNECTED)
        await service.mark_connected(record.id)
        repository.get_customer_session.return_value = _record(status=VoiceSessionState.ENDED)
        ended = await service.end_customer_session(record.id, context)
        assert ended.status is VoiceSessionState.ENDED


def test_session_validity_requires_timezone_aware_clock() -> None:
    with pytest.raises(ValueError):
        session_is_valid(_record(), now=datetime.now(), ttl=timedelta(minutes=1))
