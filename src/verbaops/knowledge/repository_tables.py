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
