"""Run the permanent LiteLLM gateway contract through the local Compose stack."""

import re
import subprocess
import sys
import uuid
from collections.abc import Sequence
from os import environ
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "docker-compose.llm-gateway.yml"
GATEWAY_API_KEY = "sk-test-gateway"
WAIT_TIMEOUT_SECONDS = "120"


class LLMGatewayContractError(RuntimeError):
    """Raised when a disposable gateway contract lifecycle command fails."""


def _redact_output(value: str) -> str:
    """Keep failure diagnostics useful without echoing credentials or auth headers."""

    secrets = {
        GATEWAY_API_KEY,
        environ.get("VERBAOPS_LLM__API_KEY", ""),
        environ.get("OPENAI_API_KEY", ""),
        environ.get("ANTHROPIC_API_KEY", ""),
    }
    redacted = value
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[redacted]")
    redacted = re.sub(r"(?i)(authorization:\s*bearer\s+)[^\s;]+", r"\1[redacted]", redacted)
    redacted = re.sub(r"(?i)(https?://)[^/\s:@]+:[^@\s]+@", r"\1[redacted]@", redacted)
    return redacted[-4000:]


def run_command(command: Sequence[str], *, env: dict[str, str] | None = None) -> str:
    """Run one contract lifecycle command without exposing its captured output."""

    completed = subprocess.run(
        list(command),
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        diagnostics = _redact_output(f"{completed.stdout}\n{completed.stderr}").strip()
        suffix = f"\n{diagnostics}" if diagnostics else ""
        raise LLMGatewayContractError(
            f"LLM gateway contract command failed with exit {completed.returncode}{suffix}"
        )
    return completed.stdout


def compose_command(project: str, *arguments: str) -> list[str]:
    """Build a Compose invocation isolated by a unique project name."""

    return [
        "docker",
        "compose",
        "--project-name",
        project,
        "-f",
        str(COMPOSE_FILE),
        *arguments,
    ]


def gateway_host_port(port_output: str) -> int:
    """Parse the Docker-assigned host port returned by `docker compose port`."""

    match = re.search(r":(\d+)\s*$", port_output.strip())
    if match is None:
        raise LLMGatewayContractError("Docker did not report a gateway host port")
    return int(match.group(1))


def compose_environment(port: int) -> dict[str, str]:
    """Retain host execution settings while overriding the disposable host port."""

    environment = dict(environ)
    environment["LLM_GATEWAY_HOST_PORT"] = str(port)
    return environment


def test_environment(port: int) -> dict[str, str]:
    """Preserve process execution settings while forcing deterministic LLM settings."""

    environment = dict(environ)
    environment.update(
        {
            "VERBAOPS_LLM__API_KEY": GATEWAY_API_KEY,
            "VERBAOPS_LLM__BASE_URL": f"http://127.0.0.1:{port}/v1",
            "VERBAOPS_LLM__TIMEOUT_SECONDS": "2.0",
        }
    )
    return environment


def run_llm_gateway_contract() -> int:
    """Start, exercise, and always remove the isolated real-proxy contract stack."""

    project = f"verbaops-llm-gateway-{uuid.uuid4().hex[:12]}"
    compose_env = compose_environment(0)
    primary_error: Exception | None = None
    teardown_error: Exception | None = None
    try:
        run_command(
            compose_command(
                project,
                "up",
                "-d",
                "--wait",
                "--wait-timeout",
                WAIT_TIMEOUT_SECONDS,
                "provider-stub",
                "llm-gateway",
            ),
            env=compose_env,
        )
        port = gateway_host_port(
            run_command(compose_command(project, "port", "llm-gateway", "4000"), env=compose_env)
        )
        run_command(
            [sys.executable, "-m", "pytest", "-m", "llm_gateway_contract", "-q"],
            env=test_environment(port),
        )
    except Exception as error:
        primary_error = error
    finally:
        try:
            run_command(
                compose_command(project, "down", "--volumes", "--remove-orphans"),
                env=compose_env,
            )
        except Exception as error:
            teardown_error = error

    if primary_error is not None and teardown_error is not None:
        raise ExceptionGroup(
            "LLM gateway contract lifecycle and teardown failed", [primary_error, teardown_error]
        )
    if primary_error is not None:
        raise primary_error
    if teardown_error is not None:
        raise LLMGatewayContractError("LLM gateway contract teardown failed") from teardown_error
    return 0


def main() -> int:
    """Run the contract runner as a Python module entry point."""

    return run_llm_gateway_contract()


if __name__ == "__main__":
    raise SystemExit(main())
