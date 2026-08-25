"""Project-level contracts for the evaluation harness."""

from pathlib import Path
import subprocess


ROOT = Path(__file__).parents[2]


def test_evaluation_markers_are_registered() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "evaluation: deterministic Stage 4 evaluation tests" in pyproject
    assert "evaluation_postgres: PostgreSQL evaluation persistence tests" in pyproject


def test_evaluation_make_targets_are_present() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "eval-corpus-check:" in makefile
    assert "eval-agent:" in makefile


def test_eval_artifacts_are_ignored() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "artifacts/eval_runs/example/summary.json"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
