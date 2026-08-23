"""Unit tests for the structural PostgreSQL marker taxonomy."""

import pytest
from scripts.postgres_taxonomy import validate_postgres_classification


def test_valid_contract_classification_is_accepted() -> None:
    validate_postgres_classification(
        "tests/integration/test_commerce_postgres.py::test_schema",
        {"postgres", "contract"},
    )


def test_valid_concurrency_classification_is_accepted() -> None:
    validate_postgres_classification(
        "tests/integration/test_m2d_write_postgres.py::test_race",
        {"postgres", "concurrency"},
    )


def test_critical_race_requires_postgres_concurrency() -> None:
    with pytest.raises(ValueError, match="critical_race requires postgres and concurrency"):
        validate_postgres_classification(
            "tests/integration/test_m2d_write_postgres.py::test_race",
            {"postgres", "critical_race"},
        )


def test_contract_and_concurrency_are_mutually_exclusive() -> None:
    with pytest.raises(ValueError, match="exactly one of contract or concurrency"):
        validate_postgres_classification(
            "tests/integration/test_commerce_postgres.py::test_schema",
            {"postgres", "contract", "concurrency"},
        )


def test_real_postgres_test_without_postgres_marker_is_rejected() -> None:
    with pytest.raises(ValueError, match="must have the postgres marker"):
        validate_postgres_classification(
            "tests/integration/test_commerce_postgres.py::test_schema",
            {"contract"},
        )


def test_real_postgres_test_without_category_is_rejected() -> None:
    with pytest.raises(ValueError, match="exactly one of contract or concurrency"):
        validate_postgres_classification(
            "tests/integration/test_commerce_postgres.py::test_schema",
            {"postgres"},
        )


def test_non_postgres_test_is_not_required_to_have_database_markers() -> None:
    validate_postgres_classification("tests/api/test_health.py::test_health", set())
