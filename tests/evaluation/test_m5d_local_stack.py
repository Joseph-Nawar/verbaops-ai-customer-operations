"""Contracts for the isolated M5D local evaluation stack."""

import json
import subprocess
from pathlib import Path

import pytest
from scripts import run_m5d_grounding_sweep_local


def test_grounded_api_environment_points_to_isolated_redis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment_file = tmp_path / "local.env"
    environment_file.write_text(
        "\n".join(
            (
                "VERBAOPS_DB_USER=m5d",
                "VERBAOPS_DB_PASSWORD=local-db-password",
                "VERBAOPS_DB_NAME=m5d",
                "COMMERCE_DB_PASSWORD=local-commerce-db-password",
                "LITELLM_MASTER_KEY=local-gateway-key",
                "NOVACOMMERCE_SERVICE_TOKEN=local-commerce-token",
                "VERBAOPS_AUTH__DEVELOPMENT_TOKEN=local-dev-token",
                "VERBAOPS_AUTH__DEVELOPMENT_PRINCIPAL_ID=principal",
                "VERBAOPS_AUTH__DEVELOPMENT_TENANT_ID=tenant",
                "VERBAOPS_AUTH__DEVELOPMENT_CUSTOMER_ID=customer",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    state_file = tmp_path / "stack.json"
    state_file.write_text(
        json.dumps(
            {
                "database_port": 32770,
                "gateway_port": 32772,
                "reranker_tei_port": 32769,
                "commerce_api_port": 32771,
                "redis_port": 32773,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(run_m5d_grounding_sweep_local, "ENV_FILE", environment_file)
    monkeypatch.setattr(run_m5d_grounding_sweep_local, "STATE_FILE", state_file)

    environment, _ = run_m5d_grounding_sweep_local._local_environment()

    assert environment["VERBAOPS_REDIS__URL"] == "redis://127.0.0.1:32773/0"


def test_isolated_compose_stack_defines_redis_service() -> None:
    compose_file = Path(__file__).resolve().parents[2] / "docker-compose.m5d-b-eval.yml"

    assert "  redis:\n" in compose_file.read_text(encoding="utf-8")


def test_redis_bootstrap_does_not_restart_the_commerce_stack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def compose(*arguments: str) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, "", "")

    # The stack helper is loaded lazily to keep tests independent of Docker.
    from scripts import prepare_m5d_b_stack

    monkeypatch.setattr(prepare_m5d_b_stack, "_compose", compose)

    prepare_m5d_b_stack._ensure_redis_service()

    assert calls == [("up", "-d", "--wait", "--wait-timeout", "1200", "redis")]
