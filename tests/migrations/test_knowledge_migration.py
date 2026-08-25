from pathlib import Path


def test_knowledge_migration_is_the_only_next_verbaops_revision() -> None:
    migration = Path("migrations/versions/0004_knowledge_rag_v1.py").read_text(encoding="utf-8")

    assert 'revision = "0004_knowledge_rag_v1"' in migration
    assert 'down_revision = "0003_evaluation_v1"' in migration
    assert migration.count("op.create_table(") == 4
    for table in (
        "knowledge_documents",
        "knowledge_versions",
        "knowledge_chunks",
        "knowledge_ingestion_jobs",
    ):
        assert f'"{table}"' in migration


def test_knowledge_migration_contains_required_vector_and_lifecycle_indexes() -> None:
    migration = Path("migrations/versions/0004_knowledge_rag_v1.py").read_text(encoding="utf-8")

    assert "Vector(768)" in migration
    assert 'postgresql_using="hnsw"' in migration
    assert "vector_cosine_ops" in migration
    assert 'postgresql_using="gin"' in migration
    assert "status = 'active'" in migration
    assert "uq_knowledge_documents_tenant_slug_language" in migration
    assert "uq_knowledge_versions_document_version" in migration
    assert "uq_knowledge_chunks_version_index" in migration
