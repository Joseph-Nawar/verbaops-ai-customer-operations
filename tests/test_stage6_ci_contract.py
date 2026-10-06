"""Structural contracts for the permanent Stage 6 CI lock."""

import re
from pathlib import Path

CI_WORKFLOW = Path(".github/workflows/ci.yml")
MAKEFILE = Path("Makefile")


def _workflow() -> str:
    return CI_WORKFLOW.read_text(encoding="utf-8")


def _makefile() -> str:
    return MAKEFILE.read_text(encoding="utf-8")


def _job_body(name: str) -> str:
    match = re.search(
        rf"^  {re.escape(name)}:\n(?P<body>.*?)(?=^  [a-z0-9-]+:|\Z)",
        _workflow(),
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"CI job {name!r} is not defined"
    return match.group("body")


def _target_body(name: str) -> str:
    match = re.search(
        rf"^{re.escape(name)}:\n(?P<body>(?:\t.*\n|\n)*)",
        _makefile(),
        re.MULTILINE,
    )
    assert match is not None, f"Make target {name!r} is not defined"
    return match.group("body")


def test_stage6_make_targets_lock_the_three_permanent_gates() -> None:
    makefile = _makefile()

    for target in ("stage6-action-contract", "stage6-postgres-contract", "stage6-acceptance"):
        assert f"{target}:" in makefile

    action = _target_body("stage6-action-contract")
    for path in (
        "tests/actions",
        "tests/api/test_action_requests.py",
        "tests/api/test_conversation_actions.py",
        "tests/tools/test_proposals.py",
        "tests/agent/test_action_proposal_tools.py",
        "tests/agent/test_action_status.py",
        "tests/novacommerce/test_stage6_ticket_category.py",
        "tests/novacommerce/test_stage6_exact_reads.py",
        "tests/novacommerce/test_stage6_refunds.py",
    ):
        assert path in action
    assert "not postgres" in action
    assert "not agent_acceptance" in action
    assert "not stage6_acceptance" in action

    postgres = _target_body("stage6-postgres-contract")
    assert "$(UV) run alembic upgrade head" in postgres
    assert "$(UV) run alembic -c alembic-commerce.ini upgrade head" in postgres
    assert "tests/postgres/stage6" in postgres
    assert "tests/integration/test_m2d_write_postgres.py" in postgres
    assert 'tests/postgres/stage6 -m "postgres and concurrency"' in postgres
    assert 'test_m2d_write_postgres.py -m "postgres and concurrency"' in postgres
    assert "--ignore" not in postgres
    assert '-k "not' not in postgres

    acceptance = _target_body("stage6-acceptance")
    assert "$(UV) run python scripts/run_stage6_acceptance.py" in acceptance


def test_stage6_ci_wires_action_postgres_and_acceptance_gates() -> None:
    workflow = _workflow()

    assert "make stage6-action-contract" in _job_body("quality")

    postgres = _job_body("stage6-postgres-contract")
    assert "name: stage6-postgres-contract" in postgres
    assert "VERBAOPS_DATABASE__URL:" in postgres
    assert "NOVACOMMERCE_TEST_DATABASE_URL:" in postgres
    assert "make stage6-postgres-contract" in postgres

    acceptance = _job_body("stage6-acceptance")
    assert "name: stage6-acceptance" in acceptance
    assert "make stage6-acceptance" in acceptance
    assert "secrets." not in acceptance

    assert "pnpm smoke" in _job_body("web-quality")
    assert workflow.count("make stage6-acceptance") == 1


def test_stage6_postgres_ci_uses_separate_databases_and_runs_both_heads() -> None:
    postgres = _job_body("stage6-postgres-contract")

    assert "POSTGRES_DB: verbaops_test" in postgres
    assert "CREATE DATABASE novacommerce_test" in postgres
    assert "VERBAOPS_DATABASE__URL: postgresql+asyncpg://" in postgres
    assert "NOVACOMMERCE_TEST_DATABASE_URL: postgresql+asyncpg://" in postgres
    assert "make stage6-postgres-contract" in postgres


def test_stage6_historical_migrations_remain_the_approved_heads() -> None:
    verbaops = Path("migrations/versions/0006_action_lifecycle_v1.py").read_text(encoding="utf-8")
    commerce = Path("commerce_migrations/versions/0002_stage6_ticket_category.py").read_text(
        encoding="utf-8"
    )

    assert 'revision = "0006_action_lifecycle_v1"' in verbaops
    assert 'revision = "0002_stage6_ticket_category"' in commerce
    assert not list(Path("migrations/versions").glob("0007_*.py"))
    assert not list(Path("commerce_migrations/versions").glob("0003_*.py"))


def test_stage6_acceptance_runner_is_provider_free_and_has_a_real_suite() -> None:
    runner = Path("scripts/run_stage6_acceptance.py").read_text(encoding="utf-8")

    assert "tests/acceptance/stage6" in runner
    assert "stage6_acceptance" in runner
    assert "provider-stub:8000/v1" in runner
    assert "provider-stub" in runner
    assert "$(UV) run python scripts/run_stage6_acceptance.py" in _target_body("stage6-acceptance")


def test_stage6_acceptance_suite_contains_workflows_and_security_regressions() -> None:
    suite = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("tests/acceptance/stage6").glob("test_*.py")
    )

    for marker in (
        "reschedule",
        "ordinary_cancellation",
        "unusual_cancellation",
        "return",
        "support_ticket",
        "499.99",
        "500.00",
        "500.01",
        "self_approval",
        "cross_customer",
        "fingerprint",
        "idempotency",
    ):
        assert marker in suite.lower()
