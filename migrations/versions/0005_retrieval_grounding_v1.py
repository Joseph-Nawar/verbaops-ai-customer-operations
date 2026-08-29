"""Create Stage 5 M5B retrieval traces, candidates, and citation snapshots."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_retrieval_grounding_v1"
down_revision = "0004_knowledge_rag_v1"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)
_NOW = sa.text("now()")


def upgrade() -> None:
    op.add_column(
        "knowledge_versions",
        sa.Column("embedding_profile", sa.String(128), nullable=True),
    )
    op.add_column(
        "knowledge_versions",
        sa.Column("embedding_model", sa.String(255), nullable=True),
    )

    op.create_table(
        "retrieval_invocations",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "agent_run_id",
            _UUID,
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", _UUID, nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("retrieval_version", sa.String(255), nullable=False),
        sa.Column("strategy", sa.String(64), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("dense_candidate_count", sa.Integer, nullable=False),
        sa.Column("lexical_candidate_count", sa.Integer, nullable=False),
        sa.Column("fused_candidate_count", sa.Integer, nullable=False),
        sa.Column("reranked_candidate_count", sa.Integer, nullable=False),
        sa.Column("selected_count", sa.Integer, nullable=False),
        sa.Column("top_score", sa.Float, nullable=True),
        sa.Column("latency_ms", sa.Float, nullable=False),
        sa.Column("embedding_model", sa.String(255), nullable=True),
        sa.Column("reranker_model", sa.String(255), nullable=True),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.UniqueConstraint(
            "agent_run_id", "sequence", name="uq_retrieval_invocations_run_sequence"
        ),
        sa.CheckConstraint(
            "status IN ('succeeded', 'insufficient', 'failed')",
            name="retrieval_invocation_status_allowed",
        ),
        sa.CheckConstraint("sequence > 0", name="retrieval_invocation_sequence_positive"),
        sa.CheckConstraint(
            "dense_candidate_count >= 0",
            name="retrieval_invocation_dense_count_non_negative",
        ),
        sa.CheckConstraint(
            "lexical_candidate_count >= 0",
            name="retrieval_invocation_lexical_count_non_negative",
        ),
        sa.CheckConstraint(
            "fused_candidate_count >= 0",
            name="retrieval_invocation_fused_count_non_negative",
        ),
        sa.CheckConstraint(
            "reranked_candidate_count >= 0",
            name="retrieval_invocation_reranked_count_non_negative",
        ),
        sa.CheckConstraint(
            "selected_count >= 0",
            name="retrieval_invocation_selected_count_non_negative",
        ),
        sa.CheckConstraint("latency_ms >= 0", name="retrieval_invocation_latency_non_negative"),
    )

    op.create_index(
        "ix_retrieval_invocations_tenant_created",
        "retrieval_invocations",
        ["tenant_id", "created_at", "id"],
    )

    op.create_table(
        "retrieval_candidates",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "retrieval_invocation_id",
            _UUID,
            sa.ForeignKey("retrieval_invocations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "chunk_id",
            _UUID,
            sa.ForeignKey("knowledge_chunks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dense_rank", sa.Integer, nullable=True),
        sa.Column("dense_score", sa.Float, nullable=True),
        sa.Column("lexical_rank", sa.Integer, nullable=True),
        sa.Column("lexical_score", sa.Float, nullable=True),
        sa.Column("rrf_rank", sa.Integer, nullable=True),
        sa.Column("rrf_score", sa.Float, nullable=True),
        sa.Column("rerank_rank", sa.Integer, nullable=True),
        sa.Column("rerank_score", sa.Float, nullable=True),
        sa.Column("selected", sa.Boolean, nullable=False),
        sa.Column("evidence_key", sa.String(16), nullable=True),
        sa.UniqueConstraint(
            "retrieval_invocation_id",
            "chunk_id",
            name="uq_retrieval_candidates_invocation_chunk",
        ),
        sa.CheckConstraint(
            "dense_rank IS NULL OR dense_rank > 0", name="retrieval_candidate_dense_rank_positive"
        ),
        sa.CheckConstraint(
            "lexical_rank IS NULL OR lexical_rank > 0",
            name="retrieval_candidate_lexical_rank_positive",
        ),
        sa.CheckConstraint(
            "rrf_rank IS NULL OR rrf_rank > 0", name="retrieval_candidate_rrf_rank_positive"
        ),
        sa.CheckConstraint(
            "rerank_rank IS NULL OR rerank_rank > 0",
            name="retrieval_candidate_rerank_rank_positive",
        ),
    )

    op.create_index(
        "ix_retrieval_candidates_invocation_selected",
        "retrieval_candidates",
        ["retrieval_invocation_id", "selected"],
    )

    op.create_table(
        "message_citations",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("tenant_id", _UUID, nullable=False),
        sa.Column(
            "message_id",
            _UUID,
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "retrieval_invocation_id",
            _UUID,
            sa.ForeignKey("retrieval_invocations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "chunk_id",
            _UUID,
            sa.ForeignKey("knowledge_chunks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("document_id", _UUID, nullable=False),
        sa.Column("version_id", _UUID, nullable=False),
        sa.Column("citation_ordinal", sa.Integer, nullable=False),
        sa.Column("evidence_key", sa.String(16), nullable=False),
        sa.Column("document_title", sa.String(200), nullable=False),
        sa.Column("document_slug", sa.String(64), nullable=False),
        sa.Column("document_version", sa.String(32), nullable=False),
        sa.Column("section", sa.String(200), nullable=False),
        sa.Column("effective_date", sa.Date, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.UniqueConstraint(
            "message_id", "citation_ordinal", name="uq_message_citations_message_ordinal"
        ),
        sa.CheckConstraint("citation_ordinal > 0", name="message_citation_ordinal_positive"),
        sa.CheckConstraint(
            "length(btrim(evidence_key)) > 0", name="message_citation_key_non_empty"
        ),
    )

    op.create_index(
        "ix_message_citations_tenant_message",
        "message_citations",
        ["tenant_id", "message_id", "citation_ordinal"],
    )


def downgrade() -> None:
    op.drop_index("ix_message_citations_tenant_message", table_name="message_citations")
    op.drop_table("message_citations")
    op.drop_index("ix_retrieval_candidates_invocation_selected", table_name="retrieval_candidates")
    op.drop_table("retrieval_candidates")
    op.drop_index("ix_retrieval_invocations_tenant_created", table_name="retrieval_invocations")
    op.drop_table("retrieval_invocations")
    op.drop_column("knowledge_versions", "embedding_model")
    op.drop_column("knowledge_versions", "embedding_profile")
