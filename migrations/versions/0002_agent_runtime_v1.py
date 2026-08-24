"""Create the durable VerbaOps conversation and trace tables."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_agent_runtime_v1"
down_revision = "0001_enable_pgvector"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)
_NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("tenant_id", _UUID, nullable=False),
        sa.Column("principal_id", _UUID, nullable=False),
        sa.Column("customer_id", _UUID, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    )
    op.create_index(
        "ix_conversations_tenant_principal_updated",
        "conversations",
        ["tenant_id", "principal_id", "updated_at", "id"],
    )

    op.create_table(
        "messages",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "conversation_id",
            _UUID,
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.UniqueConstraint(
            "conversation_id", "sequence", name="uq_messages_conversation_sequence"
        ),
        sa.CheckConstraint("sequence > 0", name="message_sequence_positive"),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="message_role_allowed"),
        sa.CheckConstraint("length(btrim(content)) > 0", name="message_content_non_empty"),
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "conversation_id",
            _UUID,
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_message_id",
            _UUID,
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "assistant_message_id",
            _UUID,
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("graph_version", sa.String(255), nullable=False),
        sa.Column("prompt_version", sa.String(255), nullable=False),
        sa.Column("tool_schema_version", sa.String(255), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')", name="agent_run_status_allowed"
        ),
        sa.CheckConstraint(
            "length(btrim(graph_version)) > 0", name="agent_run_graph_version_non_empty"
        ),
        sa.CheckConstraint(
            "length(btrim(prompt_version)) > 0", name="agent_run_prompt_version_non_empty"
        ),
        sa.CheckConstraint(
            "length(btrim(tool_schema_version)) > 0",
            name="agent_run_tool_schema_version_non_empty",
        ),
    )
    op.create_index(
        "uq_agent_runs_one_running_per_conversation",
        "agent_runs",
        ["conversation_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )

    op.create_table(
        "model_calls",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "agent_run_id",
            _UUID,
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("capability_alias", sa.String(128), nullable=False),
        sa.Column("gateway_request_id", sa.String(512), nullable=True),
        sa.Column("gateway_model_id", sa.String(512), nullable=True),
        sa.Column("model", sa.String(512), nullable=True),
        sa.Column("provider", sa.String(255), nullable=True),
        sa.Column("input_tokens", sa.Integer, nullable=True),
        sa.Column("output_tokens", sa.Integer, nullable=True),
        sa.Column("total_tokens", sa.Integer, nullable=True),
        sa.Column("latency_ms", sa.Float, nullable=True),
        sa.Column("cost_usd", sa.Float, nullable=True),
        sa.Column("finish_reason", sa.String(128), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.UniqueConstraint("agent_run_id", "sequence", name="uq_model_calls_run_sequence"),
        sa.CheckConstraint("sequence > 0", name="model_call_sequence_positive"),
        sa.CheckConstraint(
            "length(btrim(capability_alias)) > 0", name="model_call_capability_non_empty"
        ),
        sa.CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="model_call_input_tokens_non_negative",
        ),
        sa.CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="model_call_output_tokens_non_negative",
        ),
        sa.CheckConstraint(
            "total_tokens IS NULL OR total_tokens >= 0",
            name="model_call_total_tokens_non_negative",
        ),
        sa.CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0", name="model_call_latency_non_negative"
        ),
        sa.CheckConstraint(
            "cost_usd IS NULL OR cost_usd >= 0", name="model_call_cost_non_negative"
        ),
        sa.CheckConstraint("status IN ('succeeded', 'failed')", name="model_call_status_allowed"),
    )

    op.create_table(
        "tool_invocations",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "agent_run_id",
            _UUID,
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("tool_call_id", sa.String(255), nullable=False),
        sa.Column("tool_name", sa.String(255), nullable=False),
        sa.Column("risk_level", sa.String(64), nullable=False),
        sa.Column("arguments_json", postgresql.JSONB, nullable=False),
        sa.Column("result_json", postgresql.JSONB, nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("latency_ms", sa.Float, nullable=True),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("agent_run_id", "sequence", name="uq_tool_invocations_run_sequence"),
        sa.CheckConstraint("sequence > 0", name="tool_invocation_sequence_positive"),
        sa.CheckConstraint("length(btrim(tool_call_id)) > 0", name="tool_call_id_non_empty"),
        sa.CheckConstraint("length(btrim(tool_name)) > 0", name="tool_name_non_empty"),
        sa.CheckConstraint("length(btrim(risk_level)) > 0", name="tool_risk_level_non_empty"),
        sa.CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0", name="tool_latency_non_negative"
        ),
        sa.CheckConstraint(
            "status IN ('proposed', 'succeeded', 'failed')", name="tool_invocation_status_allowed"
        ),
    )


def downgrade() -> None:
    op.drop_table("tool_invocations")
    op.drop_table("model_calls")
    op.drop_index("uq_agent_runs_one_running_per_conversation", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_table("messages")
    op.drop_index("ix_conversations_tenant_principal_updated", table_name="conversations")
    op.drop_table("conversations")
