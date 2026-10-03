"""SQLAlchemy models for the durable VerbaOps action lifecycle."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from verbaops.db.base import Base

_ACTIVE_STATES = "'proposed', 'awaiting_approval', 'awaiting_confirmation', "
_ACTIVE_STATES += "'ready_to_execute', 'executing', 'unresolved'"
_LIFECYCLE_STATES = (
    "'proposed', 'policy_denied', 'awaiting_approval', 'awaiting_confirmation', "
    "'ready_to_execute', 'executing', 'succeeded', 'rejected', 'failed', 'unresolved', 'expired'"
)
_EVENT_TYPES = (
    "'created', 'policy_allowed', 'policy_denied', 'customer_confirmed', 'customer_rejected', "
    "'supervisor_approved', 'supervisor_rejected', 'execution_started', 'commerce_response', "
    "'verification_succeeded', 'verification_failed', 'unresolved', 'expired', 'state_transition'"
)


class ActionRequest(Base):
    """Authoritative current state for one scoped action proposal."""

    __tablename__ = "action_requests"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_action_requests_id_tenant"),
        UniqueConstraint(
            "originating_tool_invocation_id",
            name="uq_action_requests_originating_tool_invocation",
        ),
        UniqueConstraint("idempotency_key", name="uq_action_requests_idempotency_key"),
        CheckConstraint(
            "action_type IN ('reschedule_delivery', 'cancel_order', 'initiate_return', "
            "'create_support_ticket', 'request_refund')",
            name="action_request_type_allowed",
        ),
        CheckConstraint(
            f"state IN ({_LIFECYCLE_STATES})",
            name="action_request_state_allowed",
        ),
        CheckConstraint(
            "jsonb_typeof(proposal_payload) = 'object'",
            name="action_request_payload_object",
        ),
        CheckConstraint(
            "jsonb_typeof(target_ids) = 'array'",
            name="action_request_targets_array",
        ),
        CheckConstraint(
            "proposal_fingerprint ~ '^[0-9a-f]{64}$'",
            name="action_request_fingerprint_hex",
        ),
        CheckConstraint(
            "execution_attempt_count >= 0",
            name="action_request_attempt_non_negative",
        ),
        CheckConstraint("version > 0", name="action_request_version_positive"),
        CheckConstraint(
            "expires_at > created_at",
            name="action_request_expiry_after_creation",
        ),
        CheckConstraint(
            "(policy_allowed IS NULL AND policy_reason_code IS NULL AND policy_version IS NULL "
            "AND policy_observed_at IS NULL) OR (policy_allowed IS NOT NULL "
            "AND policy_reason_code IS NOT NULL AND policy_version IS NOT NULL "
            "AND policy_observed_at IS NOT NULL)",
            name="action_request_policy_decision_consistent",
        ),
        CheckConstraint(
            "(customer_confirmation_decision IS NULL AND customer_confirmation_actor_id IS NULL "
            "AND customer_confirmation_at IS NULL AND customer_confirmation_fingerprint IS NULL) "
            "OR (confirmation_required IS TRUE "
            "AND customer_confirmation_decision IS NOT NULL "
            "AND customer_confirmation_decision IN ('confirmed', 'rejected') "
            "AND customer_confirmation_actor_id IS NOT NULL AND customer_confirmation_at IS NOT NULL "
            "AND customer_confirmation_fingerprint IS NOT NULL "
            "AND customer_confirmation_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND customer_confirmation_fingerprint = proposal_fingerprint)",
            name="action_request_confirmation_decision_consistent",
        ),
        CheckConstraint(
            "(supervisor_approval_decision IS NULL AND supervisor_approval_actor_id IS NULL "
            "AND supervisor_approval_at IS NULL AND supervisor_approval_fingerprint IS NULL) "
            "OR (approval_required IS TRUE "
            "AND supervisor_approval_decision IS NOT NULL "
            "AND supervisor_approval_decision IN ('approved', 'rejected') "
            "AND supervisor_approval_actor_id IS NOT NULL AND supervisor_approval_at IS NOT NULL "
            "AND supervisor_approval_fingerprint IS NOT NULL "
            "AND supervisor_approval_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND supervisor_approval_fingerprint = proposal_fingerprint)",
            name="action_request_approval_decision_consistent",
        ),
        CheckConstraint(
            "verification_status IS NULL OR verification_status IN "
            "('verified', 'mismatched', 'unavailable')",
            name="action_request_verification_status_allowed",
        ),
        Index(
            "uq_action_requests_active_scope_fingerprint",
            "tenant_id",
            "conversation_id",
            "customer_id",
            "proposal_fingerprint",
            unique=True,
            postgresql_where=text(f"state IN ({_ACTIVE_STATES})"),
        ),
        Index(
            "ix_action_requests_tenant_customer_state_created",
            "tenant_id",
            "customer_id",
            "state",
            "created_at",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    customer_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    proposing_principal_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    conversation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    agent_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    originating_tool_invocation_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("tool_invocations.id", ondelete="RESTRICT"),
        nullable=True,
    )
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    proposal_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    target_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    proposal_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    proposal_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, server_default="proposed")
    policy_allowed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    policy_reason_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    policy_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    policy_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmation_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    approval_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    customer_confirmation_decision: Mapped[str | None] = mapped_column(String(16))
    customer_confirmation_actor_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True)
    )
    customer_confirmation_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    customer_confirmation_fingerprint: Mapped[str | None] = mapped_column(String(64))
    supervisor_approval_decision: Mapped[str | None] = mapped_column(String(16))
    supervisor_approval_actor_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    supervisor_approval_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    supervisor_approval_fingerprint: Mapped[str | None] = mapped_column(String(64))
    idempotency_key: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    execution_attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    execution_lease_owner: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    execution_lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    commerce_resource_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    commerce_status_code: Mapped[int | None] = mapped_column(Integer)
    commerce_error_code: Mapped[str | None] = mapped_column(String(128))
    verification_status: Mapped[str | None] = mapped_column(String(16))
    verified_resource_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ActionEvent(Base):
    """Append-only bounded action audit record."""

    __tablename__ = "action_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["action_request_id", "tenant_id"],
            ["action_requests.id", "action_requests.tenant_id"],
            ondelete="RESTRICT",
            name="fk_action_events_request_tenant",
        ),
        UniqueConstraint("action_request_id", "sequence", name="uq_action_events_request_sequence"),
        CheckConstraint("sequence > 0", name="action_event_sequence_positive"),
        CheckConstraint(
            f"event_type IN ({_EVENT_TYPES})",
            name="action_event_type_allowed",
        ),
        CheckConstraint(
            f"previous_state IS NULL OR previous_state IN ({_LIFECYCLE_STATES})",
            name="action_event_previous_state_allowed",
        ),
        CheckConstraint(
            f"next_state IS NULL OR next_state IN ({_LIFECYCLE_STATES})",
            name="action_event_next_state_allowed",
        ),
        CheckConstraint(
            "proposal_fingerprint ~ '^[0-9a-f]{64}$'",
            name="action_event_fingerprint_hex",
        ),
        Index(
            "ix_action_events_tenant_action_created",
            "tenant_id",
            "action_request_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    action_request_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_principal_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    previous_state: Mapped[str | None] = mapped_column(String(32))
    next_state: Mapped[str | None] = mapped_column(String(32))
    proposal_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    reason_code: Mapped[str | None] = mapped_column(String(128))
