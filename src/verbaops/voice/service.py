"""Short-transaction customer voice-session lifecycle service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from pydantic import AnyWebsocketUrl
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from verbaops.auth.context import Role, TrustedContext, has_customer_authority
from verbaops.conversations.domain import ConversationScope
from verbaops.conversations.errors import ConversationNotFoundError
from verbaops.conversations.service import ConversationService
from verbaops.voice.domain import VoiceSessionRecord, VoiceSessionState
from verbaops.voice.errors import (
    VoiceSessionAuthorizationError,
    VoiceSessionExpiredError,
    VoiceSessionLifecycleError,
    VoiceSessionNotFoundError,
)
from verbaops.voice.models import VoiceSessionBootstrap
from verbaops.voice.repository import VoiceSessionRepository
from verbaops.voice.transport import LiveKitTokenIssuer

if TYPE_CHECKING:
    from verbaops.voice.auth import VoiceWorkerContext


_DEFAULT_SESSION_TTL = timedelta(minutes=30)
_DEFAULT_TOKEN_TTL = timedelta(minutes=5)


class VoiceSessionService:
    """Own scope checks, bounded expiry, lifecycle transitions, and bootstrap."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        conversation_service: ConversationService | None = None,
        token_issuer: LiveKitTokenIssuer | None = None,
        livekit_url: str = "wss://livekit.invalid",
        session_ttl: timedelta = _DEFAULT_SESSION_TTL,
        token_ttl: timedelta = _DEFAULT_TOKEN_TTL,
        transport_provider: str = "livekit",
        stt_provider: str = "elevenlabs_scribe_v2_realtime",
        tts_provider: str = "elevenlabs_flash_v2_5",
    ) -> None:
        if session_ttl <= timedelta(0) or token_ttl <= timedelta(0):
            raise ValueError("voice session and token TTLs must be positive")
        if token_ttl > session_ttl:
            raise ValueError("voice token TTL cannot exceed voice session TTL")
        self._session_factory = session_factory
        self._conversation_service = conversation_service
        self._token_issuer = token_issuer
        self._livekit_url = AnyWebsocketUrl(livekit_url)
        self._session_ttl = session_ttl
        self._token_ttl = token_ttl
        self._transport_provider = transport_provider
        self._stt_provider = stt_provider
        self._tts_provider = tts_provider

    @staticmethod
    def transition_allowed(current: VoiceSessionState, next_state: VoiceSessionState) -> bool:
        """Return whether a non-idempotent lifecycle transition is permitted."""

        allowed: dict[VoiceSessionState, frozenset[VoiceSessionState]] = {
            VoiceSessionState.CREATED: frozenset(
                {VoiceSessionState.CONNECTING, VoiceSessionState.ENDED}
            ),
            VoiceSessionState.CONNECTING: frozenset(
                {VoiceSessionState.CONNECTED, VoiceSessionState.ENDED}
            ),
            VoiceSessionState.CONNECTED: frozenset({VoiceSessionState.ENDED}),
            VoiceSessionState.ENDED: frozenset(),
        }
        return next_state in allowed[current]

    async def create_customer_session(
        self,
        trusted_context: TrustedContext,
        conversation_id: UUID | None,
    ) -> VoiceSessionBootstrap:
        if not has_customer_authority(trusted_context):
            raise VoiceSessionAuthorizationError()
        customer_id = trusted_context.customer_id
        if customer_id is None:
            raise VoiceSessionAuthorizationError()
        if self._conversation_service is None or self._token_issuer is None:
            raise RuntimeError("voice bootstrap dependencies are not configured")

        scope = ConversationScope(
            tenant_id=trusted_context.tenant_id,
            principal_id=trusted_context.principal_id,
        )
        if conversation_id is None:
            conversation = await self._conversation_service.create_conversation(scope, customer_id)
        else:
            try:
                conversation = await self._conversation_service.get_conversation(
                    scope, conversation_id
                )
            except ConversationNotFoundError:
                raise VoiceSessionNotFoundError() from None
            if conversation.customer_id != customer_id:
                raise VoiceSessionNotFoundError()

        now = _utc_now()
        room_identity = f"voice-room-{uuid4()}"
        participant_identity = f"voice-participant-{uuid4()}"
        async with self._session_factory() as session, session.begin():
            record = await VoiceSessionRepository(session).create_session(
                tenant_id=trusted_context.tenant_id,
                principal_id=trusted_context.principal_id,
                customer_id=customer_id,
                conversation_id=conversation.id,
                transport_provider=self._transport_provider,
                stt_provider=self._stt_provider,
                tts_provider=self._tts_provider,
                room_identity=room_identity,
                participant_identity=participant_identity,
                status=VoiceSessionState.CREATED,
                created_at=now,
            )
        try:
            room_token = await self._token_issuer.mint_customer_token(
                room_identity=record.room_identity,
                participant_identity=record.participant_identity,
                ttl=self._token_ttl,
            )
        except Exception:
            await self._end_unscoped(record.id, error_code="token_mint_failed")
            raise
        return VoiceSessionBootstrap(
            voice_session_id=record.id,
            conversation_id=record.conversation_id,
            livekit_url=self._livekit_url,
            room_token=room_token,
            token_expires_at=now + self._token_ttl,
            status=VoiceSessionState.CREATED,
        )

    async def get_customer_session(
        self,
        session_id: UUID,
        trusted_context: TrustedContext,
    ) -> VoiceSessionRecord:
        if not has_customer_authority(trusted_context):
            raise VoiceSessionAuthorizationError()
        customer_id = trusted_context.customer_id
        if customer_id is None:
            raise VoiceSessionAuthorizationError()
        async with self._session_factory() as session, session.begin():
            try:
                record = await VoiceSessionRepository(session).get_customer_session(
                    session_id,
                    trusted_context.tenant_id,
                    trusted_context.principal_id,
                    customer_id,
                )
            except VoiceSessionNotFoundError:
                raise VoiceSessionNotFoundError() from None
        self._require_valid(record)
        return record

    async def get_worker_session(
        self,
        session_id: UUID,
        worker_context: VoiceWorkerContext,
    ) -> VoiceSessionRecord:
        if getattr(worker_context, "service_name", None) != "voice_worker":
            raise VoiceSessionAuthorizationError()
        async with self._session_factory() as session, session.begin():
            record = await VoiceSessionRepository(session).get_worker_session(session_id)
        self._require_valid(record)
        return record

    async def get_connected_worker_session(
        self,
        session_id: UUID,
        worker_context: VoiceWorkerContext,
    ) -> VoiceSessionRecord:
        """Load a valid worker session that is connected for final transcripts."""

        record = await self.get_worker_session(session_id, worker_context)
        if record.status is not VoiceSessionState.CONNECTED:
            raise VoiceSessionLifecycleError()
        return record

    async def mark_connecting(self, session_id: UUID) -> VoiceSessionRecord:
        async with self._session_factory() as session, session.begin():
            repository = VoiceSessionRepository(session)
            record = await repository.get_worker_session(session_id, for_update=True)
            self._require_valid(record)
            if record.status is VoiceSessionState.CONNECTING:
                return record
            if record.status is VoiceSessionState.CONNECTED:
                return record
            if not self.transition_allowed(record.status, VoiceSessionState.CONNECTING):
                raise VoiceSessionLifecycleError()
            return await repository.update_lifecycle(
                session_id, status=VoiceSessionState.CONNECTING
            )

    async def mark_connected(self, session_id: UUID) -> VoiceSessionRecord:
        async with self._session_factory() as session, session.begin():
            repository = VoiceSessionRepository(session)
            record = await repository.get_worker_session(session_id, for_update=True)
            self._require_valid(record)
            if record.status is VoiceSessionState.CONNECTED:
                return record
            if not self.transition_allowed(record.status, VoiceSessionState.CONNECTED):
                raise VoiceSessionLifecycleError()
            return await repository.update_lifecycle(
                session_id, status=VoiceSessionState.CONNECTED, connected_at=_utc_now()
            )

    async def end_customer_session(
        self,
        session_id: UUID,
        trusted_context: TrustedContext,
    ) -> VoiceSessionRecord:
        if not has_customer_authority(trusted_context):
            raise VoiceSessionAuthorizationError()
        customer_id = trusted_context.customer_id
        if customer_id is None:
            raise VoiceSessionAuthorizationError()
        async with self._session_factory() as session, session.begin():
            repository = VoiceSessionRepository(session)
            record = await repository.get_customer_session(
                session_id,
                trusted_context.tenant_id,
                trusted_context.principal_id,
                customer_id,
                for_update=True,
            )
            if record.status is VoiceSessionState.ENDED:
                return record
            return await repository.update_lifecycle(
                session_id, status=VoiceSessionState.ENDED, ended_at=_utc_now()
            )

    def _require_valid(self, record: VoiceSessionRecord) -> None:
        if record.status is VoiceSessionState.ENDED:
            raise VoiceSessionLifecycleError()
        if not session_is_valid(record, now=_utc_now(), ttl=self._session_ttl):
            raise VoiceSessionExpiredError()

    async def _end_unscoped(self, session_id: UUID, *, error_code: str) -> None:
        async with self._session_factory() as session, session.begin():
            await VoiceSessionRepository(session).update_lifecycle(
                session_id,
                status=VoiceSessionState.ENDED,
                ended_at=_utc_now(),
                error_code=error_code,
            )


def delegated_customer_context(record: VoiceSessionRecord) -> TrustedContext:
    """Construct the fixed customer-only capability from durable session state."""

    return TrustedContext(
        tenant_id=record.tenant_id,
        principal_id=record.principal_id,
        customer_id=record.customer_id,
        roles=frozenset({Role.CUSTOMER}),
    )


def session_is_valid(record: VoiceSessionRecord, *, now: datetime, ttl: timedelta) -> bool:
    """Return whether the server-owned session remains usable under bounded TTL."""

    if record.status is VoiceSessionState.ENDED:
        return False
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now < record.created_at + ttl


def _utc_now() -> datetime:
    return datetime.now(UTC)
