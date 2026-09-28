"""Provider-free M5D contract wiring checks."""

from __future__ import annotations

import re
from pathlib import Path


def test_m5d_contract_has_standalone_provider_free_make_target() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    match = re.search(
        r"(?ms)^m5d-evaluation-contract:\n(?P<body>.*?)(?=^[a-zA-Z0-9_-]+:|\Z)", makefile
    )

    assert match is not None
    target = match.group("body")
    assert "check_rag_v02_corpus.py --split dev" in target
    assert "test_rag_v02_contract.py" in target


def test_m5d_contract_is_a_separate_provider_free_hosted_job() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    match = re.search(
        r"(?ms)^  m5d-evaluation-contract:\n(?P<body>.*?)(?=^  [a-z0-9-]+:|\Z)", workflow
    )

    assert match is not None
    job = match.group("body")
    assert "runs-on: ubuntu-24.04" in job
    assert "uv sync --locked" in job
    assert "make m5d-evaluation-contract" in job
    for forbidden in (
        "openai_api_key",
        "groq_api_key",
        "hf_token",
        "ollama",
        "vllm",
        "huggingface.co",
    ):
        assert forbidden not in job.lower()
