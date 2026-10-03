"""Create durable VerbaOps action requests and append-only events."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_action_lifecycle_v1"
down_revision = "0005_retrieval_grounding_v1"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)
_NOW = sa.text("now()")
_LIFECYCLE_STATES = (
    "'proposed', 'policy_denied', 'awaiting_approval', 'awaiting_confirmation', "
    "'ready_to_execute', 'executing', 'succeeded', 'rejected', 'failed', 'unresolved', 'expired'"
)
_ACTIVE_STATES = "'proposed', 'awaiting_approval', 'awaiting_confirmation', "
_ACTIVE_STATES += "'ready_to_execute', 'executing', 'unresolved'"
_EVENT_TYPES = (
    "'created', 'policy_allowed', 'policy_denied', 'customer_confirmed', 'customer_rejected', "
    "'supervisor_approved', 'supervisor_rejected', 'execution_started', 'commerce_response', "
    "'verification_succeeded', 'verification_failed', 'unresolved', 'expired', 'state_transition'"
)


def upgrade() -> None:
    op.create_table(
        "action_requests",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("tenant_id", _UUID, nullable=False),
        sa.Column("customer_id", _UUID, nullable=False),
        sa.Column("proposing_principal_id", _UUID, nullable=False),
        sa.Column(
            "conversation_id",
            _UUID,
            sa.ForeignKey("conversations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "agent_run_id",
            _UUID,
            sa.ForeignKey("agent_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "originating_tool_invocation_id",
            _UUID,
            sa.ForeignKey("tool_invocations.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("action_type", sa.String(32), nullable=False),
        sa.Column("proposal_payload", postgresql.JSONB, nullable=False),
        sa.Column("target_ids", postgresql.JSONB, nullable=False),
        sa.Column("proposal_schema_version", sa.String(64), nullable=False),
        sa.Column("proposal_fingerprint", sa.String(64), nullable=False),
        sa.Column("state", sa.String(32), nullable=False, server_default="proposed"),
        sa.Column("policy_allowed", sa.Boolean, nullable=True),
        sa.Column("policy_reason_code", sa.String(128), nullable=True),
        sa.Column("policy_version", sa.String(128), nullable=True),
        sa.Column("policy_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "confirmation_required", sa.Boolean, nullable=False, server_default=sa.text("false")
        ),
        sa.Column("approval_required", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("customer_confirmation_decision", sa.String(16), nullable=True),
        sa.Column("customer_confirmation_actor_id", _UUID, nullable=True),
        sa.Column("customer_confirmation_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("customer_confirmation_fingerprint", sa.String(64), nullable=True),
        sa.Column("supervisor_approval_decision", sa.String(16), nullable=True),
        sa.Column("supervisor_approval_actor_id", _UUID, nullable=True),
        sa.Column("supervisor_approval_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("supervisor_approval_fingerprint", sa.String(64), nullable=True),
        sa.Column("idempotency_key", _UUID, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("execution_attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("execution_lease_owner", _UUID, nullable=True),
        sa.Column("execution_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("commerce_resource_id", _UUID, nullable=True),
        sa.Column("commerce_status_code", sa.Integer, nullable=True),
        sa.Column("commerce_error_code", sa.String(128), nullable=True),
        sa.Column("verification_status", sa.String(16), nullable=True),
        sa.Column("verified_resource_id", _UUID, nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.UniqueConstraint("id", "tenant_id", name="uq_action_requests_id_tenant"),
        sa.UniqueConstraint(
            "originating_tool_invocation_id",
            name="uq_action_requests_originating_tool_invocation",
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_action_requests_idempotency_key"),
        sa.CheckConstraint(
            "action_type IN ('reschedule_delivery', 'cancel_order', 'initiate_return', "
            "'create_support_ticket', 'request_refund')",
            name="action_request_type_allowed",
        ),
        sa.CheckConstraint(
            f"state IN ({_LIFECYCLE_STATES})",
            name="action_request_state_allowed",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(proposal_payload) = 'object'",
            name="action_request_payload_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(target_ids) = 'array'",
            name="action_request_targets_array",
        ),
        sa.CheckConstraint(
            "proposal_fingerprint ~ '^[0-9a-f]{64}$'",
            name="action_request_fingerprint_hex",
        ),
        sa.CheckConstraint(
            "execution_attempt_count >= 0",
            name="action_request_attempt_non_negative",
        ),
        sa.CheckConstraint("version > 0", name="action_request_version_positive"),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="action_request_expiry_after_creation",
        ),
        sa.CheckConstraint(
            "(policy_allowed IS NULL AND policy_reason_code IS NULL AND policy_version IS NULL "
            "AND policy_observed_at IS NULL) OR (policy_allowed IS NOT NULL "
            "AND policy_reason_code IS NOT NULL AND policy_version IS NOT NULL "
            "AND policy_observed_at IS NOT NULL)",
            name="action_request_policy_decision_consistent",
        ),
        sa.CheckConstraint(
            "(customer_confirmation_decision IS NULL AND customer_confirmation_actor_id IS NULL "
            "AND customer_confirmation_at IS NULL AND customer_confirmation_fingerprint IS NULL) "
            "OR (confirmation_required AND customer_confirmation_decision IN ('confirmed', 'rejected') "
            "AND customer_confirmation_actor_id IS NOT NULL AND customer_confirmation_at IS NOT NULL "
            "AND customer_confirmation_fingerprint ~ '^[0-9a-f]{64}$')",
            name="action_request_confirmation_decision_consistent",
        ),
        sa.CheckConstraint(
            "(supervisor_approval_decision IS NULL AND supervisor_approval_actor_id IS NULL "
            "AND supervisor_approval_at IS NULL AND supervisor_approval_fingerprint IS NULL) "
            "OR (approval_required AND supervisor_approval_decision IN ('approved', 'rejected') "
            "AND supervisor_approval_actor_id IS NOT NULL AND supervisor_approval_at IS NOT NULL "
            "AND supervisor_approval_fingerprint ~ '^[0-9a-f]{64}$')",
            name="action_request_approval_decision_consistent",
        ),
        sa.CheckConstraint(
            "verification_status IS NULL OR verification_status IN "
            "('verified', 'mismatched', 'unavailable')",
            name="action_request_verification_status_allowed",
        ),
    )
    op.create_index(
        "uq_action_requests_active_scope_fingerprint",
        "action_requests",
        ["tenant_id", "conversation_id", "customer_id", "proposal_fingerprint"],
        unique=True,
        postgresql_where=sa.text(f"state IN ({_ACTIVE_STATES})"),
    )
    op.create_index(
        "ix_action_requests_tenant_customer_state_created",
        "action_requests",
        ["tenant_id", "customer_id", "state", "created_at", "id"],
    )

    op.create_table(
        "action_events",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("action_request_id", _UUID, nullable=False),
        sa.Column("tenant_id", _UUID, nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("actor_principal_id", _UUID, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("previous_state", sa.String(32), nullable=True),
        sa.Column("next_state", sa.String(32), nullable=True),
        sa.Column("proposal_fingerprint", sa.String(64), nullable=False),
        sa.Column("correlation_id", _UUID, nullable=True),
        sa.Column("reason_code", sa.String(128), nullable=True),
        sa.ForeignKeyConstraint(
            ["action_request_id", "tenant_id"],
            ["action_requests.id", "action_requests.tenant_id"],
            ondelete="RESTRICT",
            name="fk_action_events_request_tenant",
        ),
        sa.UniqueConstraint(
            "action_request_id", "sequence", name="uq_action_events_request_sequence"
        ),
        sa.CheckConstraint("sequence > 0", name="action_event_sequence_positive"),
        sa.CheckConstraint(
            f"event_type IN ({_EVENT_TYPES})",
            name="action_event_type_allowed",
        ),
        sa.CheckConstraint(
            f"previous_state IS NULL OR previous_state IN ({_LIFECYCLE_STATES})",
            name="action_event_previous_state_allowed",
        ),
        sa.CheckConstraint(
            f"next_state IS NULL OR next_state IN ({_LIFECYCLE_STATES})",
            name="action_event_next_state_allowed",
        ),
        sa.CheckConstraint(
            "proposal_fingerprint ~ '^[0-9a-f]{64}$'",
            name="action_event_fingerprint_hex",
        ),
    )
    op.create_index(
        "ix_action_events_tenant_action_created",
        "action_events",
        ["tenant_id", "action_request_id", "created_at", "id"],
    )

    op.execute(
        "CREATE FUNCTION reject_action_event_mutation() RETURNS trigger AS $$ "
        "BEGIN RAISE EXCEPTION 'action_events is append-only'; END; $$ LANGUAGE plpgsql"
    )
    op.execute(
        "CREATE TRIGGER trg_action_events_append_only BEFORE UPDATE OR DELETE ON action_events "
        "FOR EACH ROW EXECUTE FUNCTION reject_action_event_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_action_events_append_only ON action_events")
    op.execute("DROP FUNCTION reject_action_event_mutation()")
    op.drop_index("ix_action_events_tenant_action_created", table_name="action_events")
    op.drop_table("action_events")
    op.drop_index("ix_action_requests_tenant_customer_state_created", table_name="action_requests")
    op.drop_index("uq_action_requests_active_scope_fingerprint", table_name="action_requests")
    op.drop_table("action_requests")
