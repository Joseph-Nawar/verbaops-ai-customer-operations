"""Unit tests for the acceptance lifecycle's non-secret pure helpers."""

import pytest
from scripts.run_commerce_acceptance import AcceptanceCommandError, parse_seed_result


def test_parse_seed_result_ignores_non_json_logs() -> None:
    result = parse_seed_result(
        "INFO migration complete\ncommerce-seed-1 | "
        '{"seed": 20260821, "as_of": "2026-08-21", "fingerprint": "abc"}\n'
    )
    assert result["seed"] == 20260821
    assert result["fingerprint"] == "abc"


def test_parse_seed_result_fails_without_seed_json() -> None:
    with pytest.raises(AcceptanceCommandError):
        parse_seed_result("migration failed")
