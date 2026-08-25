"""Strict JSONL loading for the versioned evaluation corpus."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from verbaops.evaluation.models import EvaluationCase


class CorpusFormatError(ValueError):
    """Raised when a JSONL corpus line is malformed or does not validate."""


def load_cases(path: Path) -> tuple[EvaluationCase, ...]:
    """Load every nonempty JSONL line into an immutable case tuple."""

    cases: list[EvaluationCase] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw_line.strip():
            raise CorpusFormatError(f"line {line_number}: blank lines are not allowed")
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError as error:
            raise CorpusFormatError(f"line {line_number}: invalid JSON: {error.msg}") from error
        try:
            cases.append(EvaluationCase.model_validate(payload))
        except ValidationError as error:
            raise CorpusFormatError(f"line {line_number}: invalid case: {error}") from error
    return tuple(cases)
