"""Run the disposable provider-free Stage 6 black-box acceptance stack."""

from __future__ import annotations

import json
import os
import secrets
import stat
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Callable, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "docker-compose.agent-acceptance.yml"
MANIFEST = ROOT / "tests" / "acceptance" / "fixtures" / "novacommerce-scenarios.json"


class Stage6AcceptanceError(RuntimeError):
    """Raised when the isolated Stage 6 acceptance lifecycle fails."""


def _redact(value: str, secrets_to_hide: Sequence[str]) -> str:
    redacted = value
    for secret in secrets_to_hide:
        if secret:
            redacted = redacted.replace(secret, "[redacted]")
    return redacted[-4000:]


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
        raise Stage6AcceptanceError(
            f"Stage 6 acceptance command failed with exit {completed.returncode}{suffix}"
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


def _port(value: str, name: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise Stage6AcceptanceError(f"{name} must be a valid port") from error
    if not 1 <= port <= 65535:
        raise Stage6AcceptanceError(f"{name} must be a valid port")
    return port


def _compose_port(output: str, service: str) -> int:
    for line in reversed(output.splitlines()):
        if ":" in line:
            try:
                return _port(line.rsplit(":", 1)[1].strip(), f"{service} port")
            except Stage6AcceptanceError:
                continue
    raise Stage6AcceptanceError(f"Docker did not report the {service} port")


def _seed_matches_manifest(output: str) -> None:
    expected = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for line in reversed(output.splitlines()):
        try:
            value = json.loads(line.split("|", 1)[-1].strip())
        except json.JSONDecodeError:
            continue
        if (
            not isinstance(value, dict)
            or not {"seed", "fingerprint", "scenario_ids"} <= value.keys()
        ):
            continue
        if any(
            value.get(key) != expected.get(key) for key in ("seed", "fingerprint", "scenario_ids")
        ):
            raise Stage6AcceptanceError(
                "canonical Commerce seed does not match the stable manifest"
            )
        return
    raise Stage6AcceptanceError("canonical Commerce seed did not produce its manifest result")


def _provider_free_configuration() -> None:
    configuration = (ROOT / "infra" / "litellm" / "config.test.yaml").read_text(encoding="utf-8")
    if "http://provider-stub:8000/v1" not in configuration:
        raise Stage6AcceptanceError(
            "Stage 6 acceptance is not wired to the scripted local provider"
        )
    if "groq" in configuration.lower() or "api.groq.com" in configuration.lower():
        raise Stage6AcceptanceError("Stage 6 acceptance configuration contains a live provider")


def _acceptance_as_of() -> str:
    try:
        from scripts.acceptance_time import serialize_acceptance_as_of as _serialize_scripts
    except ModuleNotFoundError:  # pragma: no cover - direct script execution
        from acceptance_time import (  # type: ignore[import-not-found]
            serialize_acceptance_as_of as _serialize_mounted,
        )

        return cast(Callable[[datetime], str], _serialize_mounted)(datetime.now(UTC))
    return _serialize_scripts(datetime.now(UTC))


def run_acceptance() -> int:
    """Start one isolated stack, run the suite, and always destroy every volume."""

    _provider_free_configuration()
    api_port = _port(
        os.environ.get("STAGE6_ACCEPTANCE_API_PORT", "18022"), "STAGE6_ACCEPTANCE_API_PORT"
    )
    as_of = _acceptance_as_of()
    verbaops_password = secrets.token_urlsafe(32)
    commerce_password = secrets.token_urlsafe(32)
    commerce_token = secrets.token_urlsafe(32)
    gateway_key = secrets.token_urlsafe(32)
    customer_token = secrets.token_urlsafe(32)
    project = f"verbaops-stage6-acceptance-{uuid.uuid4().hex[:12]}"
    secrets_to_hide = [
        verbaops_password,
        commerce_password,
        commerce_token,
        gateway_key,
        customer_token,
    ]
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
        "NOVACOMMERCE_TENANT_CURRENCY": "USD",
        "VERBAOPS_LLM__API_KEY": gateway_key,
        "VERBAOPS_COMMERCE__TENANT_ID": "10000000-0000-0000-0000-000000000002",
        "VERBAOPS_AUTH__DEVELOPMENT_TOKEN": customer_token,
        "VERBAOPS_AUTH__DEVELOPMENT_PRINCIPAL_ID": "10000000-0000-0000-0000-000000000001",
        "VERBAOPS_AUTH__DEVELOPMENT_TENANT_ID": "10000000-0000-0000-0000-000000000002",
        "VERBAOPS_AUTH__DEVELOPMENT_CUSTOMER_ID": "d77809e8-6d3b-5792-9128-ff2bc88bc955",
        "AGENT_ACCEPTANCE_API_PORT": str(api_port),
        "AGENT_ACCEPTANCE_COMMERCE_PORT": "0",
        "ACCEPTANCE_AS_OF": as_of,
    }
    process_env = os.environ.copy()
    for key in list(process_env):
        if key.startswith(("VERBAOPS_", "NOVACOMMERCE_", "AGENT_ACCEPTANCE_", "ACCEPTANCE_")):
            process_env.pop(key)
    temp_path: Path | None = None
    primary_error: Exception | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix="verbaops-stage6-", suffix=".env", delete=False
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
                "240",
                "verbaops-api",
            ),
            env=process_env,
            secrets_to_hide=secrets_to_hide,
        )
        _seed_matches_manifest(
            run_command(
                compose_command(project, temp_path, "logs", "--no-color", "commerce-seed"),
                env=process_env,
                secrets_to_hide=secrets_to_hide,
            )
        )
        verbaops_db_port = _compose_port(
            run_command(
                compose_command(project, temp_path, "port", "verbaops-postgres", "5432"),
                env=process_env,
                secrets_to_hide=secrets_to_hide,
            ),
            "VerbaOps database",
        )
        commerce_port = _compose_port(
            run_command(
                compose_command(project, temp_path, "port", "commerce-api", "8000"),
                env=process_env,
                secrets_to_hide=secrets_to_hide,
            ),
            "Commerce API",
        )
        acceptance_env = os.environ.copy()
        acceptance_env.update(
            {
                "STAGE6_ACCEPTANCE_BASE_URL": f"http://127.0.0.1:{api_port}",
                "STAGE6_ACCEPTANCE_COMMERCE_BASE_URL": f"http://127.0.0.1:{commerce_port}",
                "STAGE6_ACCEPTANCE_CUSTOMER_TOKEN": customer_token,
                "STAGE6_ACCEPTANCE_SUPERVISOR_TOKEN": "stage6-supervisor-token",
                "STAGE6_ACCEPTANCE_OTHER_CUSTOMER_TOKEN": "stage6-other-customer-token",
                "STAGE6_ACCEPTANCE_COMMERCE_TOKEN": commerce_token,
                "STAGE6_ACCEPTANCE_DATABASE_URL": (
                    "postgresql+asyncpg://verbaops_acceptance:"
                    f"{verbaops_password}@127.0.0.1:{verbaops_db_port}/verbaops_acceptance"
                ),
                "STAGE6_ACCEPTANCE_SCENARIO_MANIFEST": str(MANIFEST),
            }
        )
        output = run_command(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/acceptance/stage6",
                "-m",
                "stage6_acceptance",
                "-q",
            ],
            env=acceptance_env,
            secrets_to_hide=secrets_to_hide,
        )
        summaries = [line.strip() for line in output.splitlines() if line.strip()]
        if summaries:
            print(f"Stage 6 acceptance: {summaries[-1]}")
        print("Stage 6 model: scripted local provider-stub only; no external provider inference.")
    except Exception as error:
        primary_error = error
    teardown_error: Exception | None = None
    try:
        if temp_path is not None:
            run_command(
                compose_command(project, temp_path, "down", "--volumes", "--remove-orphans"),
                env=process_env,
                secrets_to_hide=secrets_to_hide,
            )
    except Exception as error:
        teardown_error = error
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    if primary_error is not None and teardown_error is not None:
        raise ExceptionGroup(
            "Stage 6 acceptance and teardown failed", [primary_error, teardown_error]
        )
    if primary_error is not None:
        raise primary_error
    if teardown_error is not None:
        raise Stage6AcceptanceError("Stage 6 acceptance teardown failed") from teardown_error
    return 0


def main() -> int:
    return run_acceptance()


if __name__ == "__main__":
    raise SystemExit(main())
