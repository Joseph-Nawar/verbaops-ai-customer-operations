"""Static revision-chain contracts for the VerbaOps action lifecycle migration."""

from pathlib import Path

MIGRATION = Path("migrations/versions/0006_action_lifecycle_v1.py")


def test_action_lifecycle_is_the_next_additive_verbaops_revision() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "0006_action_lifecycle_v1"' in migration
    assert 'down_revision = "0005_retrieval_grounding_v1"' in migration
    assert migration.count("op.create_table(") == 2
    assert '"action_requests"' in migration
    assert '"action_events"' in migration


def test_action_migration_has_database_uniqueness_and_append_only_protection() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")

    assert "uq_action_requests_originating_tool_invocation" in migration
    assert "uq_action_requests_active_scope_fingerprint" in migration
    assert "RESTRICT" in migration
    assert "trg_action_events_append_only" in migration
    assert "DROP TRIGGER" in migration
    assert "DROP FUNCTION" in migration
