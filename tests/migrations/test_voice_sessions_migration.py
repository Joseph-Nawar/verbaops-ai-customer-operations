"""Static contracts for the additive Stage 7 persistence migration."""

from pathlib import Path

MIGRATION = Path("migrations/versions/0007_voice_sessions_v1.py")
HISTORICAL = Path("migrations/versions/0006_action_lifecycle_v1.py")


def test_voice_migration_is_the_only_additive_revision_after_stage6() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "0007_voice_sessions_v1"' in migration
    assert 'down_revision = "0006_action_lifecycle_v1"' in migration
    assert migration.count('"voice_sessions"') >= 1
    assert "agent_runs" in migration
    assert "uq_agent_runs_voice_session_turn" in migration


def test_voice_migration_does_not_edit_or_replace_historical_stage6_revision() -> None:
    historical = HISTORICAL.read_text(encoding="utf-8")
    assert 'revision = "0006_action_lifecycle_v1"' in historical
    assert 'down_revision = "0005_retrieval_grounding_v1"' in historical
    assert "action_requests" in historical
    assert "action_events" in historical


def test_voice_migration_has_no_forbidden_durable_voice_fields() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    forbidden = ("roles", "claims", "room_token", "access_token", "raw_audio", "provider_payload")
    assert not any(f'"{field}"' in migration for field in forbidden)
