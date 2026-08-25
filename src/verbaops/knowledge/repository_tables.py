"""SQLAlchemy table definitions for the knowledge repository."""

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID

metadata = sa.MetaData()

knowledge_documents = sa.Table(
    "knowledge_documents",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("slug", sa.String(64), nullable=False),
    sa.Column("title", sa.String(200), nullable=False),
    sa.Column("document_type", sa.String(32), nullable=False),
    sa.Column("language", sa.String(16), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)

knowledge_versions = sa.Table(
    "knowledge_versions",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("document_id", UUID(as_uuid=True), nullable=False),
    sa.Column("version", sa.String(32), nullable=False),
    sa.Column("effective_date", sa.Date, nullable=False),
    sa.Column("status", sa.String(24), nullable=False),
    sa.Column("source_content", sa.Text, nullable=False),
    sa.Column("source_hash", sa.String(64), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("activated_at", sa.DateTime(timezone=True)),
    sa.Column("failure_code", sa.String(64)),
    sa.Column("embedding_profile", sa.String(128)),
    sa.Column("embedding_model", sa.String(255)),
)

knowledge_chunks = sa.Table(
    "knowledge_chunks",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("version_id", UUID(as_uuid=True), nullable=False),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("document_id", UUID(as_uuid=True), nullable=False),
    sa.Column("document_version", sa.String(32), nullable=False),
    sa.Column("section", sa.String(200), nullable=False),
    sa.Column("language", sa.String(16), nullable=False),
    sa.Column("effective_date", sa.Date, nullable=False),
    sa.Column("chunk_index", sa.Integer, nullable=False),
    sa.Column("content", sa.Text, nullable=False),
    sa.Column("content_hash", sa.String(64), nullable=False),
    sa.Column("embedding", Vector(768), nullable=False),
    sa.Column("search_vector", TSVECTOR),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)

knowledge_ingestion_jobs = sa.Table(
    "knowledge_ingestion_jobs",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("version_id", UUID(as_uuid=True), nullable=False),
    sa.Column("status", sa.String(24), nullable=False),
    sa.Column("celery_task_id", sa.String(255)),
    sa.Column("attempt_count", sa.Integer, nullable=False),
    sa.Column("failure_code", sa.String(64)),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("started_at", sa.DateTime(timezone=True)),
    sa.Column("completed_at", sa.DateTime(timezone=True)),
)

retrieval_invocations = sa.Table(
    "retrieval_invocations",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("agent_run_id", UUID(as_uuid=True), nullable=False),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
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
    sa.Column("top_score", sa.Float),
    sa.Column("latency_ms", sa.Float, nullable=False),
    sa.Column("embedding_model", sa.String(255)),
    sa.Column("reranker_model", sa.String(255)),
    sa.Column("error_code", sa.String(128)),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)

retrieval_candidates = sa.Table(
    "retrieval_candidates",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("retrieval_invocation_id", UUID(as_uuid=True), nullable=False),
    sa.Column("chunk_id", UUID(as_uuid=True), nullable=False),
    sa.Column("dense_rank", sa.Integer),
    sa.Column("dense_score", sa.Float),
    sa.Column("lexical_rank", sa.Integer),
    sa.Column("lexical_score", sa.Float),
    sa.Column("rrf_rank", sa.Integer),
    sa.Column("rrf_score", sa.Float),
    sa.Column("rerank_rank", sa.Integer),
    sa.Column("rerank_score", sa.Float),
    sa.Column("selected", sa.Boolean, nullable=False),
    sa.Column("evidence_key", sa.String(16)),
)

message_citations = sa.Table(
    "message_citations",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("message_id", UUID(as_uuid=True), nullable=False),
    sa.Column("retrieval_invocation_id", UUID(as_uuid=True)),
    sa.Column("chunk_id", UUID(as_uuid=True)),
    sa.Column("document_id", UUID(as_uuid=True), nullable=False),
    sa.Column("version_id", UUID(as_uuid=True), nullable=False),
    sa.Column("citation_ordinal", sa.Integer, nullable=False),
    sa.Column("evidence_key", sa.String(16), nullable=False),
    sa.Column("document_title", sa.String(200), nullable=False),
    sa.Column("document_slug", sa.String(64), nullable=False),
    sa.Column("document_version", sa.String(32), nullable=False),
    sa.Column("section", sa.String(200), nullable=False),
    sa.Column("effective_date", sa.Date, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)
