"""Static contracts for the VerbaOps evaluation migration."""

from pathlib import Path


def test_evaluation_migration_is_the_next_verbaops_revision() -> None:
    migration = Path("migrations/versions/0003_evaluation_v1.py").read_text(encoding="utf-8")
    assert 'revision = "0003_evaluation_v1"' in migration
    assert 'down_revision = "0002_agent_runtime_v1"' in migration
    assert '"eval_runs"' in migration
    assert '"eval_results"' in migration
    assert '"eval_cases"' not in migration


def test_evaluation_migration_contains_required_constraints_and_only_evaluation_tables() -> None:
    migration = Path("migrations/versions/0003_evaluation_v1.py").read_text(encoding="utf-8")
    assert "uq_eval_results_run_case" in migration
    assert "eval_run_id" in migration
    assert "status IN ('running', 'completed', 'failed')" in migration
    assert "case_count >= 0" in migration
    assert "latency_ms IS NULL OR latency_ms >= 0" in migration
    assert "cost_usd IS NULL OR cost_usd >= 0" in migration
