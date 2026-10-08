"""SQLAlchemy persistence for the bounded Stage 7 voice session row."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from verbaops.db.base import Base


def _uuid_column() -> Mapped[UUID]:
    return mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)


def _timestamp_column(*, nullable: bool = False) -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=nullable)


class VoiceSession(Base):
    """Durable server-owned transport session, deliberately credential-free."""

    __tablename__ = "voice_sessions"
    __table_args__ = (
        CheckConstraint(
            "transport_provider IN ('livekit')",
            name="voice_session_transport_provider_allowed",
        ),
        CheckConstraint(
            "length(btrim(stt_provider)) > 0",
            name="voice_session_stt_provider_non_empty",
        ),
        CheckConstraint(
            "length(btrim(tts_provider)) > 0",
            name="voice_session_tts_provider_non_empty",
        ),
        CheckConstraint(
            "length(btrim(room_identity)) > 0 AND length(btrim(participant_identity)) > 0",
            name="voice_session_transport_identity_non_empty",
        ),
        CheckConstraint(
            "status IN ('created', 'connecting', 'connected', 'ended')",
            name="voice_session_status_allowed",
        ),
        CheckConstraint(
            "connected_at IS NULL OR status IN ('connected', 'ended')",
            name="voice_session_connected_timestamp_consistent",
        ),
        CheckConstraint(
            "status <> 'connected' OR connected_at IS NOT NULL",
            name="voice_session_connected_timestamp_required",
        ),
        CheckConstraint(
            "ended_at IS NULL OR status = 'ended'",
            name="voice_session_ended_timestamp_consistent",
        ),
        CheckConstraint(
            "status <> 'ended' OR ended_at IS NOT NULL",
            name="voice_session_ended_timestamp_required",
        ),
        Index(
            "ix_voice_sessions_tenant_customer_status_created",
            "tenant_id",
            "customer_id",
            "status",
            "created_at",
            "id",
        ),
        Index("uq_voice_sessions_room_identity", "room_identity", unique=True),
        Index("uq_voice_sessions_participant_identity", "participant_identity", unique=True),
    )

    id: Mapped[UUID] = _uuid_column()
    tenant_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    principal_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    customer_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    conversation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    transport_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    stt_provider: Mapped[str] = mapped_column(String(128), nullable=False)
    tts_provider: Mapped[str] = mapped_column(String(128), nullable=False)
    room_identity: Mapped[str] = mapped_column(String(255), nullable=False)
    participant_identity: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = _timestamp_column()
    connected_at: Mapped[datetime | None] = _timestamp_column(nullable=True)
    ended_at: Mapped[datetime | None] = _timestamp_column(nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
