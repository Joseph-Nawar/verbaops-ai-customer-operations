"""SQLAlchemy persistence models for the M3B agent runtime records."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from verbaops.db.base import Base


def _uuid_column() -> Mapped[UUID]:
    return mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)


def _timestamp_column(*, nullable: bool = False) -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=nullable)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index(
            "ix_conversations_tenant_principal_updated",
            "tenant_id",
            "principal_id",
            "updated_at",
            "id",
        ),
    )

    id: Mapped[UUID] = _uuid_column()
    tenant_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    principal_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    customer_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = _timestamp_column()
    updated_at: Mapped[datetime] = _timestamp_column()


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence", name="uq_messages_conversation_sequence"),
        CheckConstraint("sequence > 0", name="message_sequence_positive"),
        CheckConstraint("role IN ('user', 'assistant')", name="message_role_allowed"),
        CheckConstraint("length(btrim(content)) > 0", name="message_content_non_empty"),
    )

    id: Mapped[UUID] = _uuid_column()
    conversation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _timestamp_column()


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')", name="agent_run_status_allowed"
        ),
        CheckConstraint(
            "length(btrim(graph_version)) > 0", name="agent_run_graph_version_non_empty"
        ),
        CheckConstraint(
            "length(btrim(prompt_version)) > 0", name="agent_run_prompt_version_non_empty"
        ),
        CheckConstraint(
            "length(btrim(tool_schema_version)) > 0", name="agent_run_tool_schema_version_non_empty"
        ),
        Index(
            "uq_agent_runs_one_running_per_conversation",
            "conversation_id",
            unique=True,
            postgresql_where="status = 'running'",
        ),
    )

    id: Mapped[UUID] = _uuid_column()
    conversation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_message_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    assistant_message_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    graph_version: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(255), nullable=False)
    tool_schema_version: Mapped[str] = mapped_column(String(255), nullable=False)
    started_at: Mapped[datetime] = _timestamp_column()
    completed_at: Mapped[datetime | None] = _timestamp_column(nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)


class ModelCall(Base):
    __tablename__ = "model_calls"
    __table_args__ = (
        UniqueConstraint("agent_run_id", "sequence", name="uq_model_calls_run_sequence"),
        CheckConstraint("sequence > 0", name="model_call_sequence_positive"),
        CheckConstraint(
            "length(btrim(capability_alias)) > 0", name="model_call_capability_non_empty"
        ),
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0", name="model_call_input_tokens_non_negative"
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="model_call_output_tokens_non_negative",
        ),
        CheckConstraint(
            "total_tokens IS NULL OR total_tokens >= 0", name="model_call_total_tokens_non_negative"
        ),
        CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0", name="model_call_latency_non_negative"
        ),
        CheckConstraint("cost_usd IS NULL OR cost_usd >= 0", name="model_call_cost_non_negative"),
        CheckConstraint("status IN ('succeeded', 'failed')", name="model_call_status_allowed"),
    )

    id: Mapped[UUID] = _uuid_column()
    agent_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    capability_alias: Mapped[str] = mapped_column(String(128), nullable=False)
    gateway_request_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    gateway_model_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    model: Mapped[str | None] = mapped_column(String(512), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(255), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    finish_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = _timestamp_column()


class ToolInvocation(Base):
    __tablename__ = "tool_invocations"
    __table_args__ = (
        UniqueConstraint("agent_run_id", "sequence", name="uq_tool_invocations_run_sequence"),
        CheckConstraint("sequence > 0", name="tool_invocation_sequence_positive"),
        CheckConstraint("length(btrim(tool_call_id)) > 0", name="tool_call_id_non_empty"),
        CheckConstraint("length(btrim(tool_name)) > 0", name="tool_name_non_empty"),
        CheckConstraint("length(btrim(risk_level)) > 0", name="tool_risk_level_non_empty"),
        CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="tool_latency_non_negative"),
        CheckConstraint(
            "status IN ('proposed', 'succeeded', 'failed')", name="tool_invocation_status_allowed"
        ),
    )

    id: Mapped[UUID] = _uuid_column()
    agent_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_call_id: Mapped[str] = mapped_column(String(255), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(255), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(64), nullable=False)
    arguments_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result_json: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = _timestamp_column()
    completed_at: Mapped[datetime | None] = _timestamp_column(nullable=True)
