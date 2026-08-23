"""Behavioral tests for the disposable LiteLLM gateway contract runner."""

import sys
from collections.abc import Sequence
from pathlib import Path

import pytest
import scripts.run_llm_gateway_contract as runner
from scripts.run_llm_gateway_contract import LLMGatewayContractError


def test_runner_starts_a_unique_waited_stack_and_runs_only_marked_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[list[str], dict[str, str] | None]] = []

    def fake_run(command: Sequence[str], *, env: dict[str, str] | None = None) -> str:
        commands.append((list(command), env))
        if command[-3:] == ["port", "llm-gateway", "4000"]:
            return "127.0.0.1:49123\n"
        return "5 passed in 0.1s"

    monkeypatch.setattr(runner, "run_command", fake_run)

    assert runner.run_llm_gateway_contract() == 0

    up_command, compose_environment = commands[0]
    assert up_command[:6] == [
        "docker",
        "compose",
        "--project-name",
        up_command[3],
        "-f",
        str(runner.COMPOSE_FILE),
    ]
    assert up_command[3].startswith("verbaops-llm-gateway-")
    assert up_command[6:] == [
        "up",
        "-d",
        "--wait",
        "--wait-timeout",
        "120",
        "provider-stub",
        "llm-gateway",
    ]
    assert compose_environment is not None
    assert compose_environment["LLM_GATEWAY_HOST_PORT"] == "0"

    port_command, _ = commands[1]
    assert port_command[6:] == ["port", "llm-gateway", "4000"]

    test_command, test_environment = commands[2]
    assert test_command == [
        sys.executable,
        "-m",
        "pytest",
        "-m",
        "llm_gateway_contract",
        "-q",
    ]
    assert test_environment == {
        "VERBAOPS_LLM__API_KEY": "sk-test-gateway",
        "VERBAOPS_LLM__BASE_URL": "http://127.0.0.1:49123/v1",
        "VERBAOPS_LLM__TIMEOUT_SECONDS": "2.0",
    }


def test_runner_always_removes_volumes_orphans_and_temp_resources_after_test_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[list[str], dict[str, str] | None]] = []

    def fake_run(command: Sequence[str], *, env: dict[str, str] | None = None) -> str:
        commands.append((list(command), env))
        if command[-3:] == ["port", "llm-gateway", "4000"]:
            return "127.0.0.1:49124\n"
        if "pytest" in command:
            raise LLMGatewayContractError("marked suite failed")
        return ""

    monkeypatch.setattr(runner, "run_command", fake_run)

    with pytest.raises(LLMGatewayContractError, match="marked suite failed"):
        runner.run_llm_gateway_contract()

    down_command, down_environment = commands[-1]
    assert down_command[-3:] == ["down", "--volumes", "--remove-orphans"]
    assert down_environment is not None
    assert down_environment["LLM_GATEWAY_HOST_PORT"] == "0"


def test_runner_preserves_primary_and_teardown_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(command: Sequence[str], *, env: dict[str, str] | None = None) -> str:
        del env
        if "up" in command:
            raise LLMGatewayContractError("gateway setup failed")
        if "down" in command:
            raise LLMGatewayContractError("gateway teardown failed")
        return ""

    monkeypatch.setattr(runner, "run_command", fake_run)

    with pytest.raises(ExceptionGroup) as caught:
        runner.run_llm_gateway_contract()

    assert {str(error) for error in caught.value.exceptions} == {
        "gateway setup failed",
        "gateway teardown failed",
    }


def test_compose_command_uses_the_repository_gateway_stack() -> None:
    command = runner.compose_command("gateway-test", "down")

    assert command == [
        "docker",
        "compose",
        "--project-name",
        "gateway-test",
        "-f",
        str(Path(runner.COMPOSE_FILE)),
        "down",
    ]


def test_compose_environment_keeps_host_execution_settings_but_pytest_stays_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "C:\\test-bin")
    monkeypatch.setenv("USERPROFILE", "C:\\test-profile")

    compose_environment = runner.compose_environment(39125)

    assert compose_environment["PATH"] == "C:\\test-bin"
    assert compose_environment["USERPROFILE"] == "C:\\test-profile"
    assert compose_environment["LLM_GATEWAY_HOST_PORT"] == "39125"
    assert runner.test_environment(39125) == {
        "VERBAOPS_LLM__API_KEY": "sk-test-gateway",
        "VERBAOPS_LLM__BASE_URL": "http://127.0.0.1:39125/v1",
        "VERBAOPS_LLM__TIMEOUT_SECONDS": "2.0",
    }
