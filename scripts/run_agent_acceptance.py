"""Run the disposable full VerbaOps M3E backend acceptance stack."""

import json
import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "docker-compose.agent-acceptance.yml"
MANIFEST = ROOT / "tests" / "acceptance" / "fixtures" / "novacommerce-scenarios.json"


class AgentAcceptanceError(RuntimeError):
    """Raised when the disposable agent acceptance lifecycle fails."""


def _redact(value: str, secrets_to_hide: Sequence[str]) -> str:
    redacted = value
    for secret in secrets_to_hide:
        if secret:
            redacted = redacted.replace(secret, "[redacted]")
    return re.sub(r"(?i)(authorization:\s*bearer\s+)[^\s;]+", r"\1[redacted]", redacted)[-4000:]


def run_command(
    command: Sequence[str], *, env: dict[str, str], secrets_to_hide: Sequence[str]
) -> str:
    completed = subprocess.run(
        list(command),
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        diagnostics = _redact(f"{completed.stdout}\n{completed.stderr}", secrets_to_hide).strip()
        suffix = f": {diagnostics}" if diagnostics else ""
        raise AgentAcceptanceError(
            f"agent acceptance command failed with exit {completed.returncode}{suffix}"
        )
    return completed.stdout


def compose_command(project: str, env_file: Path, *arguments: str) -> list[str]:
    return [
        "docker",
        "compose",
        "--project-name",
        project,
        "--env-file",
        str(env_file),
        "-f",
        str(COMPOSE_FILE),
        *arguments,
    ]


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise AgentAcceptanceError("AGENT_ACCEPTANCE_API_PORT must be a valid port") from error
    if not 1 <= port <= 65535:
        raise AgentAcceptanceError("AGENT_ACCEPTANCE_API_PORT must be a valid port")
    return port


def _compose_port(output: str) -> int:
    match = re.search(r":(\d+)\s*$", output.strip())
    if match is None:
        raise AgentAcceptanceError("Docker did not report the VerbaOps database port")
    return int(match.group(1))


def _seed_result(output: str) -> dict[str, object]:
    for line in reversed(output.splitlines()):
        try:
            value = json.loads(line.split("|", 1)[-1].strip())
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and {"seed", "fingerprint", "scenario_ids"}.issubset(value):
            return value
    raise AgentAcceptanceError("canonical Commerce seed did not produce its manifest result")


def run_acceptance() -> int:
    api_port = _port(os.environ.get("AGENT_ACCEPTANCE_API_PORT", "18020"))
    verbaops_password = secrets.token_urlsafe(32)
    commerce_password = secrets.token_urlsafe(32)
    commerce_token = secrets.token_urlsafe(32)
    development_token = secrets.token_urlsafe(32)
    gateway_key = secrets.token_urlsafe(32)
    principal_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    customer_id = "d77809e8-6d3b-5792-9128-ff2bc88bc955"
    project = f"verbaops-agent-acceptance-{uuid.uuid4().hex[:12]}"
    env = os.environ.copy()
    temp_path: Path | None = None
    secrets_to_hide = [
        verbaops_password,
        commerce_password,
        commerce_token,
        development_token,
        gateway_key,
    ]
    primary_error: Exception | None = None
    compose_env = {
        "VERBAOPS_DB_NAME": "verbaops_acceptance",
        "VERBAOPS_DB_USER": "verbaops_acceptance",
        "VERBAOPS_DB_PASSWORD": verbaops_password,
        "VERBAOPS_DB_PORT": "0",
        "VERBAOPS_DATABASE__URL": (
            "postgresql+asyncpg://verbaops_acceptance:"
            f"{verbaops_password}@verbaops-postgres:5432/verbaops_acceptance"
        ),
        "COMMERCE_DB_NAME": "commerce_acceptance",
        "COMMERCE_DB_USER": "commerce_acceptance",
        "COMMERCE_DB_PASSWORD": commerce_password,
        "NOVACOMMERCE_DATABASE__URL": (
            "postgresql+asyncpg://commerce_acceptance:"
            f"{commerce_password}@commerce-postgres:5432/commerce_acceptance"
        ),
        "NOVACOMMERCE_SERVICE_TOKEN": commerce_token,
        "VERBAOPS_LLM__API_KEY": gateway_key,
        "VERBAOPS_AUTH__DEVELOPMENT_TOKEN": development_token,
        "VERBAOPS_AUTH__DEVELOPMENT_PRINCIPAL_ID": principal_id,
        "VERBAOPS_AUTH__DEVELOPMENT_TENANT_ID": tenant_id,
        "VERBAOPS_AUTH__DEVELOPMENT_CUSTOMER_ID": customer_id,
        "AGENT_ACCEPTANCE_API_PORT": str(api_port),
    }
    compose_env.update(
        {
            "AGENT_ACCEPTANCE_SCENARIO_MANIFEST": "/acceptance/novacommerce-scenarios.json",
        }
    )
    compose_process_env = env.copy()
    for key in list(compose_process_env):
        if key.startswith(("VERBAOPS_", "NOVACOMMERCE_", "AGENT_ACCEPTANCE_")):
            compose_process_env.pop(key)
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix="verbaops-agent-acceptance-",
            suffix=".env",
            delete=False,
        ) as env_file:
            temp_path = Path(env_file.name)
            with suppress(NotImplementedError, OSError):
                os.chmod(temp_path, stat.S_IRUSR | stat.S_IWUSR)
            for key, value in compose_env.items():
                env_file.write(f"{key}={value}\n")

        run_command(
            compose_command(
                project,
                temp_path,
                "up",
                "-d",
                "--wait",
                "--wait-timeout",
                "180",
                "verbaops-api",
            ),
            env=compose_process_env,
            secrets_to_hide=secrets_to_hide,
        )
        seed = _seed_result(
            run_command(
                compose_command(project, temp_path, "logs", "--no-color", "commerce-seed"),
                env=compose_process_env,
                secrets_to_hide=secrets_to_hide,
            )
        )
        expected = json.loads(MANIFEST.read_text(encoding="utf-8"))
        if any(
            seed.get(key) != expected.get(key) for key in ("seed", "fingerprint", "scenario_ids")
        ):
            raise AgentAcceptanceError("canonical Commerce seed does not match the stable manifest")
        db_port = _compose_port(
            run_command(
                compose_command(project, temp_path, "port", "verbaops-postgres", "5432"),
                env=compose_process_env,
                secrets_to_hide=secrets_to_hide,
            )
        )
        acceptance_env = env.copy()
        acceptance_env.update(
            {
                "AGENT_ACCEPTANCE_BASE_URL": f"http://127.0.0.1:{api_port}",
                "AGENT_ACCEPTANCE_TOKEN": development_token,
                "AGENT_ACCEPTANCE_DATABASE_URL": (
                    "postgresql+asyncpg://verbaops_acceptance:"
                    f"{verbaops_password}@127.0.0.1:{db_port}/verbaops_acceptance"
                ),
                "AGENT_ACCEPTANCE_SCENARIO_MANIFEST": str(MANIFEST),
            }
        )
        output = run_command(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/acceptance/agent",
                "-m",
                "agent_acceptance",
                "-q",
            ],
            env=acceptance_env,
            secrets_to_hide=secrets_to_hide,
        )
        summary = [line.strip() for line in output.splitlines() if line.strip()]
        if summary:
            print(f"Agent acceptance: {summary[-1]}")
    except Exception as error:
        primary_error = error
    teardown_error: Exception | None = None
    try:
        if temp_path is not None:
            run_command(
                compose_command(project, temp_path, "down", "--volumes", "--remove-orphans"),
                env=compose_process_env,
                secrets_to_hide=secrets_to_hide,
            )
    except Exception as error:
        teardown_error = error
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    if primary_error is not None and teardown_error is not None:
        raise ExceptionGroup(
            "agent acceptance and teardown failed", [primary_error, teardown_error]
        )
    if primary_error is not None:
        raise primary_error
    if teardown_error is not None:
        raise AgentAcceptanceError("agent acceptance teardown failed") from teardown_error
    return 0


def main() -> int:
    return run_acceptance()


if __name__ == "__main__":
    raise SystemExit(main())
