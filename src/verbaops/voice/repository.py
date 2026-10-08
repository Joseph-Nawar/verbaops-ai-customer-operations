"""Transaction-scoped persistence operations for voice sessions."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from verbaops.voice.domain import VoiceSessionRecord, VoiceSessionState
from verbaops.voice.errors import VoiceSessionNotFoundError
from verbaops.voice.persistence import VoiceSession


class VoiceSessionRepository:
    """Repository whose caller owns the short transaction and locking boundary."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_session(
        self,
        *,
        tenant_id: UUID,
        principal_id: UUID,
        customer_id: UUID,
        conversation_id: UUID,
        transport_provider: str,
        stt_provider: str,
        tts_provider: str,
        room_identity: str,
        participant_identity: str,
        status: VoiceSessionState,
        created_at: datetime,
    ) -> VoiceSessionRecord:
        row = VoiceSession(
            tenant_id=tenant_id,
            principal_id=principal_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            transport_provider=transport_provider,
            stt_provider=stt_provider,
            tts_provider=tts_provider,
            room_identity=room_identity,
            participant_identity=participant_identity,
            status=status.value,
            created_at=created_at,
        )
        self._session.add(row)
        await self._session.flush()
        return _record(row)

    async def get_customer_session(
        self,
        session_id: UUID,
        tenant_id: UUID,
        principal_id: UUID,
        customer_id: UUID,
        *,
        for_update: bool = False,
    ) -> VoiceSessionRecord:
        statement = select(VoiceSession).where(
            VoiceSession.id == session_id,
            VoiceSession.tenant_id == tenant_id,
            VoiceSession.principal_id == principal_id,
            VoiceSession.customer_id == customer_id,
        )
        return await self._get(statement, for_update=for_update)

    async def get_worker_session(
        self, session_id: UUID, *, for_update: bool = False
    ) -> VoiceSessionRecord:
        return await self._get(
            select(VoiceSession).where(VoiceSession.id == session_id),
            for_update=for_update,
        )

    async def update_lifecycle(
        self,
        session_id: UUID,
        *,
        status: VoiceSessionState,
        connected_at: datetime | None = None,
        ended_at: datetime | None = None,
        error_code: str | None = None,
    ) -> VoiceSessionRecord:
        row = await self._row_by_id(session_id, for_update=True)
        row.status = status.value
        if connected_at is not None:
            row.connected_at = connected_at
        if ended_at is not None:
            row.ended_at = ended_at
        if error_code is not None:
            row.error_code = error_code
        await self._session.flush()
        return _record(row)

    async def _get(
        self, statement: Select[tuple[VoiceSession]], *, for_update: bool
    ) -> VoiceSessionRecord:
        typed_statement = statement
        if for_update:
            typed_statement = typed_statement.with_for_update()
        row = await self._session.scalar(typed_statement)
        if row is None:
            raise VoiceSessionNotFoundError()
        return _record(row)

    async def _row_by_id(self, session_id: UUID, *, for_update: bool) -> VoiceSession:
        statement = select(VoiceSession).where(VoiceSession.id == session_id)
        if for_update:
            statement = statement.with_for_update()
        row = await self._session.scalar(statement)
        if row is None:
            raise VoiceSessionNotFoundError()
        return row


def _record(row: VoiceSession) -> VoiceSessionRecord:
    return VoiceSessionRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        principal_id=row.principal_id,
        customer_id=row.customer_id,
        conversation_id=row.conversation_id,
        transport_provider=row.transport_provider,
        stt_provider=row.stt_provider,
        tts_provider=row.tts_provider,
        room_identity=row.room_identity,
        participant_identity=row.participant_identity,
        status=VoiceSessionState(row.status),
        created_at=row.created_at,
        connected_at=row.connected_at,
        ended_at=row.ended_at,
        error_code=row.error_code,
    )
