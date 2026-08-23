"""Unit tests for the acceptance lifecycle runner."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
import scripts.run_commerce_acceptance as runner
from scripts.acceptance_time import parse_acceptance_as_of, serialize_acceptance_as_of
from scripts.run_commerce_acceptance import AcceptanceCommandError, parse_seed_result


def _successful_command_factory(commands: list[list[str]]) -> Callable[..., str]:
    expected = json.loads(runner.MANIFEST.read_text(encoding="utf-8"))

    def fake(command: list[str], *, env: dict[str, str] | None = None) -> str:
        commands.append(command)
        if "logs" in command:
            return json.dumps(expected)
        if "pytest" in command:
            return "18 passed in 0.1s"
        return ""

    return fake


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


@pytest.mark.parametrize(
    ("value", "expected"),
    [("18010", 18010), ("12345", 12345)],
)
def test_validate_port_accepts_valid_ports(value: str, expected: int) -> None:
    assert runner.validate_port(value) == expected


@pytest.mark.parametrize("value", ["abc", "0", "65536", "-1"])
def test_validate_port_rejects_invalid_ports(value: str) -> None:
    with pytest.raises(ValueError, match="port"):
        runner.validate_port(value)


def test_acceptance_time_is_utc_second_precision_and_round_trips() -> None:
    value = serialize_acceptance_as_of(datetime(2030, 1, 2, 3, 4, 5, 999999, tzinfo=UTC))
    assert value == "2030-01-02T03:04:05Z"
    assert parse_acceptance_as_of(value) == datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)


def test_acceptance_time_rejects_naive_values() -> None:
    with pytest.raises(ValueError, match="timezone"):
        parse_acceptance_as_of("2030-01-02T03:04:05")


def test_setup_failure_still_tears_down_and_removes_temp_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []
    env_files: list[str] = []

    def fake(command: list[str], *, env: dict[str, str] | None = None) -> str:
        commands.append(command)
        if "--env-file" in command:
            env_files.append(command[command.index("--env-file") + 1])
        if "up" in command:
            raise AcceptanceCommandError("setup failed")
        return ""

    monkeypatch.setattr(runner, "run_command", fake)
    with pytest.raises(AcceptanceCommandError, match="setup failed"):
        runner.run_acceptance()

    assert any("down" in command for command in commands)
    assert any("--volumes" in command and "--remove-orphans" in command for command in commands)
    assert env_files
    assert all(not Path(path).exists() for path in env_files)


def test_test_failure_still_tears_down(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    def fake(command: list[str], *, env: dict[str, str] | None = None) -> str:
        commands.append(command)
        if "logs" in command:
            return json.dumps(json.loads(runner.MANIFEST.read_text(encoding="utf-8")))
        if "pytest" in command:
            raise AcceptanceCommandError("HTTP suite failed")
        return ""

    monkeypatch.setattr(runner, "run_command", fake)
    with pytest.raises(AcceptanceCommandError, match="HTTP suite failed"):
        runner.run_acceptance()
    assert any("down" in command for command in commands)


def test_successful_lifecycle_tears_down(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(runner, "run_command", _successful_command_factory(commands))

    assert runner.run_acceptance() == 0
    assert any("down" in command for command in commands)


def test_one_run_level_acceptance_as_of_reaches_compose_and_pytest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []
    environments: list[dict[str, str]] = []

    def fake(command: list[str], *, env: dict[str, str] | None = None) -> str:
        commands.append(command)
        assert env is not None
        environments.append(env)
        if "logs" in command:
            return json.dumps(json.loads(runner.MANIFEST.read_text(encoding="utf-8")))
        if "pytest" in command:
            return "18 passed in 0.1s"
        return ""

    monkeypatch.setenv("ACCEPTANCE_AS_OF", "2031-04-05T06:07:08Z")
    monkeypatch.setattr(runner, "run_command", fake)
    assert runner.run_acceptance() == 0
    assert environments
    assert {environment["ACCEPTANCE_AS_OF"] for environment in environments} == {
        "2031-04-05T06:07:08Z"
    }


def test_dual_failure_preserves_primary_and_teardown_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def fake(command: list[str], *, env: dict[str, str] | None = None) -> str:
        commands.append(command)
        if "up" in command:
            raise AcceptanceCommandError("primary acceptance failure")
        if "down" in command:
            raise AcceptanceCommandError("teardown failure")
        return ""

    monkeypatch.setattr(runner, "run_command", fake)
    with pytest.raises(ExceptionGroup) as caught:
        runner.run_acceptance()

    messages = {str(error) for error in caught.value.exceptions}
    assert messages == {"primary acceptance failure", "teardown failure"}


def test_generated_credentials_are_not_in_output_or_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    password = "password-that-must-not-leak"
    token = "token-that-must-not-leak"
    generated = iter([password, token])
    monkeypatch.setattr("secrets.token_urlsafe", lambda _length: next(generated))

    def fake(command: list[str], *, env: dict[str, str] | None = None) -> str:
        if "up" in command:
            raise AcceptanceCommandError("command failed")
        return ""

    monkeypatch.setattr(runner, "run_command", fake)
    with pytest.raises(AcceptanceCommandError) as caught:
        runner.run_acceptance()

    captured = capsys.readouterr()
    assert password not in captured.out + captured.err + str(caught.value)
    assert token not in captured.out + captured.err + str(caught.value)


def test_temporary_configuration_requests_owner_only_permissions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []
    modes: list[int] = []
    monkeypatch.setattr(runner, "run_command", _successful_command_factory(commands))
    monkeypatch.setattr("os.chmod", lambda _path, mode: modes.append(mode))

    runner.run_acceptance()

    assert modes
    assert modes[0] & 0o777 == 0o600
