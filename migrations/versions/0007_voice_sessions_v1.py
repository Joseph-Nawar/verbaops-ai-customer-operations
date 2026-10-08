"""Create bounded Stage 7 voice sessions and AgentRun voice provenance."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_voice_sessions_v1"
down_revision = "0006_action_lifecycle_v1"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)
_NOW = sa.text("now()")


def upgrade() -> None:
    """Add only the durable voice boundary; no audio, token, role, or provider payload."""

    op.create_table(
        "voice_sessions",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("tenant_id", _UUID, nullable=False),
        sa.Column("principal_id", _UUID, nullable=False),
        sa.Column("customer_id", _UUID, nullable=False),
        sa.Column(
            "conversation_id",
            _UUID,
            sa.ForeignKey("conversations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("transport_provider", sa.String(32), nullable=False),
        sa.Column("stt_provider", sa.String(128), nullable=False),
        sa.Column("tts_provider", sa.String(128), nullable=False),
        sa.Column("room_identity", sa.String(255), nullable=False),
        sa.Column("participant_identity", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.CheckConstraint(
            "transport_provider IN ('livekit')",
            name="voice_session_transport_provider_allowed",
        ),
        sa.CheckConstraint(
            "length(btrim(stt_provider)) > 0",
            name="voice_session_stt_provider_non_empty",
        ),
        sa.CheckConstraint(
            "length(btrim(tts_provider)) > 0",
            name="voice_session_tts_provider_non_empty",
        ),
        sa.CheckConstraint(
            "length(btrim(room_identity)) > 0 AND length(btrim(participant_identity)) > 0",
            name="voice_session_transport_identity_non_empty",
        ),
        sa.CheckConstraint(
            "status IN ('created', 'connecting', 'connected', 'ended')",
            name="voice_session_status_allowed",
        ),
        sa.CheckConstraint(
            "connected_at IS NULL OR status IN ('connected', 'ended')",
            name="voice_session_connected_timestamp_consistent",
        ),
        sa.CheckConstraint(
            "status <> 'connected' OR connected_at IS NOT NULL",
            name="voice_session_connected_timestamp_required",
        ),
        sa.CheckConstraint(
            "ended_at IS NULL OR status = 'ended'",
            name="voice_session_ended_timestamp_consistent",
        ),
        sa.CheckConstraint(
            "status <> 'ended' OR ended_at IS NOT NULL",
            name="voice_session_ended_timestamp_required",
        ),
    )
    op.create_index(
        "ix_voice_sessions_tenant_customer_status_created",
        "voice_sessions",
        ["tenant_id", "customer_id", "status", "created_at", "id"],
    )
    op.create_index(
        "uq_voice_sessions_room_identity",
        "voice_sessions",
        ["room_identity"],
        unique=True,
    )
    op.create_index(
        "uq_voice_sessions_participant_identity",
        "voice_sessions",
        ["participant_identity"],
        unique=True,
    )

    op.add_column(
        "agent_runs",
        sa.Column("interaction_mode", sa.String(16), nullable=False, server_default="text"),
    )
    op.add_column("agent_runs", sa.Column("voice_session_id", _UUID, nullable=True))
    op.add_column("agent_runs", sa.Column("voice_turn_id", _UUID, nullable=True))
    op.alter_column("agent_runs", "interaction_mode", server_default=None)
    op.create_foreign_key(
        "fk_agent_runs_voice_session_id",
        "agent_runs",
        "voice_sessions",
        ["voice_session_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "agent_run_interaction_mode_allowed",
        "agent_runs",
        "interaction_mode IN ('text', 'voice')",
    )
    op.create_check_constraint(
        "agent_run_provenance_consistent",
        "agent_runs",
        "(interaction_mode = 'text' AND voice_session_id IS NULL AND voice_turn_id IS NULL) "
        "OR (interaction_mode = 'voice' AND voice_session_id IS NOT NULL "
        "AND voice_turn_id IS NOT NULL)",
    )
    op.create_index(
        "uq_agent_runs_voice_session_turn",
        "agent_runs",
        ["voice_session_id", "voice_turn_id"],
        unique=True,
        postgresql_where=sa.text("voice_session_id IS NOT NULL AND voice_turn_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Reverse only the additive Stage 7 objects."""

    op.drop_index("uq_agent_runs_voice_session_turn", table_name="agent_runs")
    op.drop_constraint("agent_run_provenance_consistent", "agent_runs", type_="check")
    op.drop_constraint("agent_run_interaction_mode_allowed", "agent_runs", type_="check")
    op.drop_constraint("fk_agent_runs_voice_session_id", "agent_runs", type_="foreignkey")
    op.drop_column("agent_runs", "voice_turn_id")
    op.drop_column("agent_runs", "voice_session_id")
    op.drop_column("agent_runs", "interaction_mode")
    op.drop_index("uq_voice_sessions_participant_identity", table_name="voice_sessions")
    op.drop_index("uq_voice_sessions_room_identity", table_name="voice_sessions")
    op.drop_index("ix_voice_sessions_tenant_customer_status_created", table_name="voice_sessions")
    op.drop_table("voice_sessions")
