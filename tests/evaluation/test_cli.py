"""CLI, documentation, and hosted evaluation-contract checks."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_corpus_checker_runs_against_committed_corpus() -> None:
    result = subprocess.run(
        ["uv", "run", "python", "scripts/check_eval_corpus.py"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Cases: 120" in result.stdout
    assert "dev: 96" in result.stdout
    assert "release_holdout: 24" in result.stdout


def test_evaluation_cli_is_deterministic_and_provider_free() -> None:
    script = (ROOT / "scripts/run_agent_eval.py").read_text(encoding="utf-8")
    assert "DeterministicFixtureAdapter" in script
    assert "baseline" not in script.lower()
    assert "provider" in script
    assert "asyncio.run" in script


def test_readme_and_evaluation_plan_state_m4a_boundary() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    plan = (ROOT / "docs/evaluation/evaluation-plan.md").read_text(encoding="utf-8")
    for command in ("make eval-corpus-check", "make eval-agent"):
        assert command in readme
    assert "M4A builds the evaluation system" in readme
    assert "first genuine model baseline is M4B" in readme
    assert "implementation status" in plan.casefold()


def test_ci_has_evaluation_contract_and_preserves_stage3_jobs() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "  evaluation-contract:" in workflow
    assert "name: evaluation-contract" in workflow
    assert "image: pgvector/pgvector:0.8.6-pg16-bookworm" in workflow
    assert "uv run alembic upgrade head" in workflow
    assert "make eval-corpus-check" in workflow
    assert 'uv run pytest -m "evaluation_postgres"' in workflow
    assert "secrets." not in workflow
    for job in (
        "quality",
        "postgres-contract",
        "postgres-concurrency",
        "postgres-m3b",
        "postgres-m3d",
        "commerce-acceptance",
        "commerce-client-contract",
        "llm-gateway-contract",
        "agent-acceptance",
        "web-quality",
        "docker-build",
    ):
        assert f"  {job}:" in workflow
