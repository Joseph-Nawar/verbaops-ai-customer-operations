"""Create the Stage 4 evaluation run and result tables."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_evaluation_v1"
down_revision = "0002_agent_runtime_v1"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)
_JSONB = postgresql.JSONB
_NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "eval_runs",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("dataset_version", sa.String(255), nullable=False),
        sa.Column("dataset_sha256", sa.String(64), nullable=False),
        sa.Column("git_sha", sa.String(255), nullable=False),
        sa.Column("environment", sa.String(255), nullable=False),
        sa.Column("capability_alias", sa.String(128), nullable=False),
        sa.Column("gateway_model_id", sa.String(512), nullable=True),
        sa.Column("model", sa.String(512), nullable=True),
        sa.Column("provider", sa.String(255), nullable=True),
        sa.Column("prompt_version", sa.String(255), nullable=False),
        sa.Column("graph_version", sa.String(255), nullable=False),
        sa.Column("tool_schema_version", sa.String(255), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("case_count", sa.Integer, nullable=False),
        sa.Column("summary_json", _JSONB, nullable=True),
        sa.Column("latency_ms", sa.Float, nullable=True),
        sa.Column("cost_usd", sa.Float, nullable=True),
        sa.CheckConstraint(
            "length(btrim(dataset_version)) > 0", name="eval_run_dataset_version_non_empty"
        ),
        sa.CheckConstraint("length(btrim(git_sha)) > 0", name="eval_run_git_sha_non_empty"),
        sa.CheckConstraint("length(btrim(environment)) > 0", name="eval_run_environment_non_empty"),
        sa.CheckConstraint(
            "length(btrim(capability_alias)) > 0", name="eval_run_capability_non_empty"
        ),
        sa.CheckConstraint(
            "length(btrim(prompt_version)) > 0", name="eval_run_prompt_version_non_empty"
        ),
        sa.CheckConstraint(
            "length(btrim(graph_version)) > 0", name="eval_run_graph_version_non_empty"
        ),
        sa.CheckConstraint(
            "length(btrim(tool_schema_version)) > 0", name="eval_run_tool_schema_version_non_empty"
        ),
        sa.CheckConstraint("case_count >= 0", name="eval_run_case_count_non_negative"),
        sa.CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0", name="eval_run_latency_non_negative"
        ),
        sa.CheckConstraint("cost_usd IS NULL OR cost_usd >= 0", name="eval_run_cost_non_negative"),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')", name="eval_run_status_allowed"
        ),
    )
    op.create_table(
        "eval_results",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "eval_run_id", _UUID, sa.ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("case_id", sa.String(255), nullable=False),
        sa.Column("split", sa.String(32), nullable=False),
        sa.Column("category", sa.String(128), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("passed", sa.Boolean, nullable=False),
        sa.Column("expected_tool", sa.String(128), nullable=True),
        sa.Column("observed_tools", _JSONB, nullable=False),
        sa.Column("expected_arguments", _JSONB, nullable=False),
        sa.Column("observed_arguments", _JSONB, nullable=False),
        sa.Column("expected_outcome", _JSONB, nullable=False),
        sa.Column("observed_outcome", _JSONB, nullable=False),
        sa.Column("metric_details", _JSONB, nullable=False),
        sa.Column("failure_reasons", _JSONB, nullable=False),
        sa.Column("latency_ms", sa.Float, nullable=True),
        sa.Column("cost_usd", sa.Float, nullable=True),
        sa.Column(
            "agent_run_id",
            _UUID,
            sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.UniqueConstraint("eval_run_id", "case_id", name="uq_eval_results_run_case"),
        sa.CheckConstraint("length(btrim(case_id)) > 0", name="eval_result_case_id_non_empty"),
        sa.CheckConstraint("length(btrim(split)) > 0", name="eval_result_split_non_empty"),
        sa.CheckConstraint("length(btrim(category)) > 0", name="eval_result_category_non_empty"),
        sa.CheckConstraint("length(btrim(language)) > 0", name="eval_result_language_non_empty"),
        sa.CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0", name="eval_result_latency_non_negative"
        ),
        sa.CheckConstraint(
            "cost_usd IS NULL OR cost_usd >= 0", name="eval_result_cost_non_negative"
        ),
    )


def downgrade() -> None:
    op.drop_table("eval_results")
    op.drop_table("eval_runs")
