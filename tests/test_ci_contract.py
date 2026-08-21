"""Contract tests for the repository's CI quality and build gates."""

import re
from pathlib import Path

WORKFLOW = Path(".github/workflows/ci.yml")


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
    assert "uv run pytest --cov=verbaops --cov=novacommerce --cov-report=term-missing" in text
    assert "--cov=novacommerce" in text
    assert "uv run pre-commit run --all-files" in text
    assert text.index("uv run ruff check .") < text.index("uv run ruff format --check .")
    assert text.index("uv run ruff format --check .") < text.index("uv run mypy src tests")
    assert text.index("uv run mypy src tests") < text.index("uv run pytest --cov=verbaops")
    assert text.index("uv run pytest --cov=verbaops") < text.index(
        "uv run pre-commit run --all-files"
    )
    assert "0.12.5" in text
    assert "fail_under = 80" in Path("pyproject.toml").read_text(encoding="utf-8")


def test_ci_docker_job_is_quality_gated_and_does_not_publish() -> None:
    text = workflow_text()

    assert "docker-build:" in text
    assert "needs: quality" in text
    assert "docker build --target runtime -t verbaops:ci ." in text
    assert "docker/build-push-action" not in text
    assert "docker login" not in text
    assert "docker push" not in text
    assert "docker compose" not in text
