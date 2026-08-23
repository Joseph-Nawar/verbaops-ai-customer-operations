"""Migration definition remains extension-only in M1D."""

from pathlib import Path


def test_initial_migration_only_manages_vector_extension() -> None:
    migration = Path("migrations/versions/0001_enable_pgvector.py")
    text = migration.read_text(encoding="utf-8")

    assert "CREATE EXTENSION IF NOT EXISTS vector" in text
    assert "DROP EXTENSION IF EXISTS vector" in text
    assert "create_table" not in text
