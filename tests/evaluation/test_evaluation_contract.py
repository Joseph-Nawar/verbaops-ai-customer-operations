"""Project-level contracts for the evaluation harness."""

import subprocess
from pathlib import Path

import pytest

from verbaops.evaluation.cases import load_cases
from verbaops.evaluation.live import LiveCorpusContractError, assert_live_corpus_contract
from verbaops.evaluation.models import ConversationTurn

ROOT = Path(__file__).parents[2]


def test_evaluation_markers_are_registered() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "evaluation: deterministic Stage 4 evaluation tests" in pyproject
    assert "evaluation_postgres: PostgreSQL evaluation persistence tests" in pyproject


def test_evaluation_make_targets_are_present() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "eval-corpus-check:" in makefile
    assert "eval-agent:" in makefile


def test_live_corpus_contract_accepts_current_cases_and_rejects_history() -> None:
    cases = load_cases(ROOT / "evals/agent/v0.1/cases.jsonl")
    assert_live_corpus_contract(cases)

    invalid = cases[0].model_copy(
        update={
            "conversation": (
                ConversationTurn(role="assistant", content="Earlier answer."),
                *cases[0].conversation,
            )
        }
    )
    with pytest.raises(LiveCorpusContractError, match="exactly one user turn"):
        assert_live_corpus_contract((invalid,))


def test_eval_artifacts_are_ignored() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "artifacts/eval_runs/example/summary.json"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
