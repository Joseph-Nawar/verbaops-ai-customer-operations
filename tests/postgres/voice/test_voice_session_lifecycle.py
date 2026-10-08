"""PostgreSQL lifecycle and scope contracts for M7A.2."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from verbaops.auth.context import Role, TrustedContext
from verbaops.voice.domain import VoiceSessionState
from verbaops.voice.errors import VoiceSessionLifecycleError, VoiceSessionNotFoundError
from verbaops.voice.repository import VoiceSessionRepository
from verbaops.voice.service import VoiceSessionService

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.contract]


async def _seed_conversation(engine: AsyncEngine) -> dict[str, object]:
    now = datetime.now(UTC)
    values: dict[str, object] = {
        "tenant_id": uuid4(),
        "principal_id": uuid4(),
        "customer_id": uuid4(),
        "conversation_id": uuid4(),
        "now": now,
    }
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO conversations "
                "(id, tenant_id, principal_id, customer_id, created_at, updated_at) "
                "VALUES (:conversation_id, :tenant_id, :principal_id, :customer_id, :now, :now)"
            ),
            values,
        )
    return values


def _context(values: dict[str, object]) -> TrustedContext:
    return TrustedContext(
        tenant_id=values["tenant_id"],
        principal_id=values["principal_id"],
        customer_id=values["customer_id"],
        roles=frozenset({Role.CUSTOMER}),
    )


@pytest.mark.asyncio
async def test_repository_scopes_reads_and_end_is_idempotent(postgres_engine: AsyncEngine) -> None:
    values = await _seed_conversation(postgres_engine)
    factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    context = _context(values)

    async with factory() as session, session.begin():
        record = await VoiceSessionRepository(session).create_session(
            tenant_id=context.tenant_id,
            principal_id=context.principal_id,
            customer_id=context.customer_id,
            conversation_id=values["conversation_id"],
            transport_provider="livekit",
            stt_provider="stt",
            tts_provider="tts",
            room_identity=f"room-{uuid4()}",
            participant_identity=f"participant-{uuid4()}",
            status=VoiceSessionState.CREATED,
            created_at=datetime.now(UTC),
        )

    async with factory() as session, session.begin():
        loaded = await VoiceSessionRepository(session).get_customer_session(
            record.id, context.tenant_id, context.principal_id, context.customer_id
        )
    assert loaded.id == record.id

    foreign = TrustedContext(
        tenant_id=context.tenant_id,
        principal_id=uuid4(),
        customer_id=uuid4(),
        roles=frozenset({Role.CUSTOMER}),
    )
    async with factory() as session, session.begin():
        with pytest.raises(VoiceSessionNotFoundError):
            await VoiceSessionRepository(session).get_customer_session(
                record.id, foreign.tenant_id, foreign.principal_id, foreign.customer_id
            )

    service = VoiceSessionService(factory, session_ttl=timedelta(minutes=30))
    ended = await service.end_customer_session(record.id, context)
    repeated = await service.end_customer_session(record.id, context)
    assert ended.status is VoiceSessionState.ENDED
    assert repeated.status is VoiceSessionState.ENDED
    assert repeated.ended_at == ended.ended_at


@pytest.mark.asyncio
async def test_ended_session_cannot_reopen_or_connect(postgres_engine: AsyncEngine) -> None:
    values = await _seed_conversation(postgres_engine)
    factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    context = _context(values)
    service = VoiceSessionService(factory, session_ttl=timedelta(minutes=30))

    async with factory() as session, session.begin():
        record = await VoiceSessionRepository(session).create_session(
            tenant_id=context.tenant_id,
            principal_id=context.principal_id,
            customer_id=context.customer_id,
            conversation_id=values["conversation_id"],
            transport_provider="livekit",
            stt_provider="stt",
            tts_provider="tts",
            room_identity=f"room-{uuid4()}",
            participant_identity=f"participant-{uuid4()}",
            status=VoiceSessionState.CREATED,
            created_at=datetime.now(UTC),
        )

    await service.end_customer_session(record.id, context)
    with pytest.raises(VoiceSessionLifecycleError):
        await service.mark_connecting(record.id)
