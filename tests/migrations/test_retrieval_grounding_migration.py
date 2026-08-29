from pathlib import Path

MIGRATION = Path("migrations/versions/0005_retrieval_grounding_v1.py")


def test_retrieval_grounding_migration_is_next_verbaops_revision() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "0005_retrieval_grounding_v1"' in migration
    assert 'down_revision = "0004_knowledge_rag_v1"' in migration
    assert 'sa.Column("embedding_profile", sa.String(128), nullable=True)' in migration
    assert 'sa.Column("embedding_model", sa.String(255), nullable=True)' in migration
    assert migration.count("op.create_table(") == 3
    for table in ("retrieval_invocations", "retrieval_candidates", "message_citations"):
        assert f'"{table}"' in migration


def test_retrieval_grounding_migration_contains_audit_constraints_and_indexes() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")

    assert "uq_retrieval_invocations_run_sequence" in migration
    assert "uq_retrieval_candidates_invocation_chunk" in migration
    assert "uq_message_citations_message_ordinal" in migration
    assert "status IN ('succeeded', 'insufficient', 'failed')" in migration
    assert "agent_run_id" in migration
    assert "retrieval_invocation_id" in migration
    assert "document_title" in migration
    assert "effective_date" in migration
    assert "dense_candidate_count >= 0" in migration
    assert "latency_ms >= 0" in migration


def test_commerce_migration_remains_independent() -> None:
    migration = Path("commerce_migrations/versions/0001_create_commerce_schema.py").read_text(
        encoding="utf-8"
    )

    assert 'revision = "0001_create_commerce_schema"' in migration
    assert "down_revision = None" in migration
