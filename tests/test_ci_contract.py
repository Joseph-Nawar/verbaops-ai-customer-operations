"""Contract tests for the repository's CI quality and build gates."""

import re
from pathlib import Path

WORKFLOW = Path(".github/workflows/ci.yml")
MAKEFILE = Path("Makefile")


def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_ci_workflow_has_safe_triggers_permissions_and_action_pins() -> None:
    text = workflow_text()

    assert "name: CI" in text
    assert "pull_request:" in text
    assert "push:" in text
    assert "branches: [main]" in text or "- main" in text
    assert "workflow_dispatch:" in text
    assert "pull_request_target" not in text
    assert "permissions:\n  contents: read" in text
    assert "permissions: write" not in text
    assert "secrets." not in text

    uses = re.findall(r"^\s+uses:\s+([^\s#]+)(?:\s+#\s*(.*))?$", text, re.MULTILINE)
    assert uses
    references = [reference.rsplit("@", maxsplit=1)[-1] for reference, _ in uses]
    assert all(re.fullmatch(r"[0-9a-f]{40}", reference) for reference in references)
    assert all(comment for _, comment in uses)
    assert "3d3c42e5aac5ba805825da76410c181273ba90b1" in text
    assert "c771a70e6277c0a99b617c7a806ffedaca235ff9" in text
    assert "persist-credentials: false" in text


def test_ci_quality_order_and_locked_uv_build_contract() -> None:
    text = workflow_text()

    assert "quality:" in text
    assert "timeout-minutes:" in text
    assert "concurrency:" in text
    assert "cancel-in-progress: true" in text
    assert "uv python install" in text
    assert "uv lock --check" in text
    assert "uv sync --locked" in text
    assert "uv run ruff check ." in text
    assert "uv run ruff format --check ." in text
    assert "uv run mypy src tests" in text
    assert (
        'uv run pytest -m "not postgres and not commerce_acceptance and not commerce_client_contract and not llm_gateway_contract and not agent_acceptance" --cov=verbaops --cov=novacommerce --cov-report=term-missing'
        in text
    )
    assert "--cov=novacommerce" in text
    assert "uv run pre-commit run --all-files" in text
    assert text.index("uv run ruff check .") < text.index("uv run ruff format --check .")
    assert text.index("uv run ruff format --check .") < text.index("uv run mypy src tests")
    assert text.index("uv run mypy src tests") < text.index(
        'uv run pytest -m "not postgres and not commerce_acceptance and not commerce_client_contract and not llm_gateway_contract and not agent_acceptance"'
    )
    assert text.index(
        'uv run pytest -m "not postgres and not commerce_acceptance and not commerce_client_contract and not llm_gateway_contract and not agent_acceptance"'
    ) < text.index("uv run pre-commit run --all-files")
    assert "0.12.5" in text
    assert "fail_under = 80" in Path("pyproject.toml").read_text(encoding="utf-8")


def test_ci_docker_job_is_quality_gated_and_does_not_publish() -> None:
    text = workflow_text()

    assert "docker-build:" in text
    assert "needs: [quality, postgres-contract, postgres-concurrency]" in text
    assert "docker build --target runtime -t verbaops:ci ." in text
    assert "docker/build-push-action" not in text
    assert "docker login" not in text
    assert "docker push" not in text
    assert "docker compose" not in text


def test_local_check_excludes_postgres_and_exposes_parity_targets() -> None:
    text = MAKEFILE.read_text(encoding="utf-8")

    assert (
        '$(UV) run pytest -m "not postgres and not commerce_acceptance and not commerce_client_contract and not llm_gateway_contract and not agent_acceptance"'
        in text
    )
    assert "llm-gateway-contract:" in text
    assert "postgres-contract:" in text
    assert "postgres-concurrency:" in text
    assert "postgres-critical-race:" in text
    assert "commerce-contract-check:" in text
    assert "commerce-contract-update:" in text
    assert "agent-acceptance:" in text
    assert "scripts/require_test_database.py" in text


def test_postgres_targets_require_external_test_database_url() -> None:
    script = Path("scripts/require_test_database.py").read_text(encoding="utf-8")
    assert "NOVACOMMERCE_TEST_DATABASE_URL" in script
    assert "postgresql+asyncpg://" in script
    assert "raise SystemExit" in script


def test_hosted_postgres_jobs_have_exact_marker_passes_and_isolated_services() -> None:
    text = workflow_text()

    assert "postgres-contract:" in text
    assert "postgres-concurrency:" in text
    assert "name: postgres-contract" in text
    assert "name: postgres-concurrency" in text
    assert text.count("image: postgres:16") + text.count("image: postgres:16.6-alpine") >= 2
    assert text.count("NOVACOMMERCE_TEST_DATABASE_URL:") >= 2
    assert text.count('uv run pytest -m "postgres and contract and not m3b"') == 1
    assert text.count('uv run pytest -m "postgres and concurrency and not m3b"') == 1
    assert (
        text.count('uv run pytest -m "postgres and concurrency and critical_race and not m3b"') == 2
    )
    assert "alembic -c alembic-commerce.ini upgrade head" in text
    assert "health-cmd" in text
    assert "continue-on-error" not in text
    assert "rerunfailures" not in text
    assert "pytest-rerunfailures" not in text


def test_quality_uses_normal_database_independent_path_and_contract_check() -> None:
    text = workflow_text()

    assert (
        'uv run pytest -m "not postgres and not commerce_acceptance and not commerce_client_contract and not llm_gateway_contract and not agent_acceptance" --cov=verbaops --cov=novacommerce'
        in text
    )
    assert "uv run mypy src tests scripts" in text
    assert "make commerce-contract-check" in text


def test_ci_has_independent_credential_free_llm_gateway_contract_job() -> None:
    text = workflow_text()

    for job_name in (
        "quality",
        "postgres-contract",
        "postgres-concurrency",
        "docker-build",
        "commerce-acceptance",
        "commerce-client-contract",
        "agent-acceptance",
    ):
        assert f"  {job_name}:" in text

    assert (
        'uv run pytest -m "not postgres and not commerce_acceptance and not commerce_client_contract and not llm_gateway_contract and not agent_acceptance"'
        in text
    )

    job_match = re.search(
        r"^  llm-gateway-contract:\n(?P<body>.*?)(?=^  [a-z0-9-]+:|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert job_match is not None

    job = job_match.group("body")
    assert "name: llm-gateway-contract" in job
    assert "runs-on: ubuntu-24.04" in job
    assert "timeout-minutes:" in job
    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in job
    assert "astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9" in job
    assert 'version: "0.12.5"' in job
    assert "uv python install" in job
    assert "uv lock --check" in job
    assert "uv sync --locked" in job
    assert "make llm-gateway-contract" in job
    assert "needs:" not in job
    assert "env:" not in job


def test_ci_has_independent_agent_acceptance_job() -> None:
    text = workflow_text()
    job_match = re.search(
        r"^  agent-acceptance:\n(?P<body>.*?)(?=^  [a-z0-9-]+:|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert job_match is not None
    job = job_match.group("body")
    assert "name: agent-acceptance" in job
    assert "runs-on: ubuntu-24.04" in job
    assert "uv lock --check" in job
    assert "uv sync --locked" in job
    assert "make agent-acceptance" in job
    assert "secrets." not in job
    assert "env:" not in job


def test_ci_has_isolated_m3d_postgres_job() -> None:
    text = workflow_text()
    job_match = re.search(
        r"^  postgres-m3d:\n(?P<body>.*?)(?=^  [a-z0-9-]+:|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert job_match is not None
    job = job_match.group("body")
    assert "name: postgres-m3d" in job
    assert "image: pgvector/pgvector:0.8.6-pg16-bookworm" in job
    assert "VERBAOPS_DATABASE__URL:" in job
    assert "NOVACOMMERCE_TEST_DATABASE_URL:" in job
    assert "uv run alembic upgrade head" in job
    assert 'uv run pytest -m "postgres and m3d"' in job
    assert "continue-on-error" not in job


def test_ci_has_pinned_node24_web_quality_job() -> None:
    text = workflow_text()
    job_match = re.search(
        r"^  web-quality:\n(?P<body>.*?)(?=^  [a-z0-9-]+:|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert job_match is not None
    job = job_match.group("body")
    assert "name: web-quality" in job
    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in job
    assert "actions/setup-node@820762786026740c76f36085b0efc47a31fe5020" in job
    assert "pnpm/action-setup@ff378ebe6b225b0680b81c1ad4498ae0d1d3a5e3" in job
    assert 'node-version: "24.x"' in job
    assert 'version: "11.23.0"' in job
    assert "pnpm install --frozen-lockfile" in job
    for command in ("pnpm lint", "pnpm typecheck", "pnpm test", "pnpm build", "pnpm smoke"):
        assert command in job
