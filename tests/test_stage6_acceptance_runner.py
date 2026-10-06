"""Tests for deterministic Stage 6 acceptance-stack orchestration."""

from datetime import UTC, datetime

from scripts.acceptance_time import parse_acceptance_as_of
from scripts.run_stage6_acceptance import _acceptance_as_of


def test_stage6_runner_uses_one_current_utc_run_timestamp() -> None:
    value = _acceptance_as_of()
    parsed = parse_acceptance_as_of(value)
    assert value.endswith("Z")
    assert abs((parsed - datetime.now(UTC)).total_seconds()) < 5
