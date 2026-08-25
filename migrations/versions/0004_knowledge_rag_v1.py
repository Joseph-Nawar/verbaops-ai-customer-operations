"""Create the Stage 5 versioned knowledge and ingestion tables."""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "0004_knowledge_rag_v1"
down_revision = "0003_evaluation_v1"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)
_NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "knowledge_documents",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("tenant_id", _UUID, nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("document_type", sa.String(32), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.UniqueConstraint(
            "tenant_id", "slug", "language", name="uq_knowledge_documents_tenant_slug_language"
        ),
        sa.CheckConstraint("length(btrim(slug)) > 0", name="knowledge_document_slug_non_empty"),
        sa.CheckConstraint("length(btrim(title)) > 0", name="knowledge_document_title_non_empty"),
        sa.CheckConstraint(
            "length(btrim(document_type)) > 0", name="knowledge_document_type_non_empty"
        ),
        sa.CheckConstraint(
            "length(btrim(language)) > 0", name="knowledge_document_language_non_empty"
        ),
    )
    op.create_table(
        "knowledge_versions",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "document_id",
            _UUID,
            sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("effective_date", sa.Date, nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("source_content", sa.Text, nullable=False),
        sa.Column("source_hash", sa.CHAR(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.UniqueConstraint(
            "document_id", "version", name="uq_knowledge_versions_document_version"
        ),
        sa.CheckConstraint(
            "status IN ('processing', 'ready', 'active', 'superseded', 'failed', 'quarantined')",
            name="knowledge_version_status_allowed",
        ),
        sa.CheckConstraint("length(source_hash) = 64", name="knowledge_version_source_hash_length"),
    )
    op.create_index(
        "uq_knowledge_versions_one_active",
        "knowledge_versions",
        ["document_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "version_id",
            _UUID,
            sa.ForeignKey("knowledge_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", _UUID, nullable=False),
        sa.Column("document_id", _UUID, nullable=False),
        sa.Column("document_version", sa.String(32), nullable=False),
        sa.Column("section", sa.String(200), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("effective_date", sa.Date, nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("content_hash", sa.CHAR(64), nullable=False),
        sa.Column("embedding", Vector(768), nullable=False),
        sa.Column("search_vector", postgresql.TSVECTOR, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.UniqueConstraint("version_id", "chunk_index", name="uq_knowledge_chunks_version_index"),
        sa.CheckConstraint("chunk_index >= 0", name="knowledge_chunk_index_non_negative"),
        sa.CheckConstraint("length(btrim(content)) > 0", name="knowledge_chunk_content_non_empty"),
        sa.CheckConstraint("length(content_hash) = 64", name="knowledge_chunk_hash_length"),
    )
    op.create_index(
        "ix_knowledge_chunks_embedding_hnsw",
        "knowledge_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_knowledge_chunks_search_vector_gin",
        "knowledge_chunks",
        ["search_vector"],
        postgresql_using="gin",
    )
    op.create_table(
        "knowledge_ingestion_jobs",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("tenant_id", _UUID, nullable=False),
        sa.Column(
            "version_id",
            _UUID,
            sa.ForeignKey("knowledge_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("celery_task_id", sa.String(255), nullable=True),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'succeeded', 'failed', 'quarantined')",
            name="knowledge_job_status_allowed",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="knowledge_job_attempts_non_negative"),
    )


def downgrade() -> None:
    op.drop_table("knowledge_ingestion_jobs")
    op.drop_index("ix_knowledge_chunks_search_vector_gin", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_embedding_hnsw", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_index("uq_knowledge_versions_one_active", table_name="knowledge_versions")
    op.drop_table("knowledge_versions")
    op.drop_table("knowledge_documents")
