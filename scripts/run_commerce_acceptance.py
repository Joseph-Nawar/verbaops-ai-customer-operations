"""Run the permanent black-box NovaCommerce acceptance gate."""

import json
import os
import secrets
import stat
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.acceptance_time import parse_acceptance_as_of, serialize_acceptance_as_of

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "docker-compose.acceptance.yml"
MANIFEST = ROOT / "tests" / "acceptance" / "fixtures" / "novacommerce-scenarios.json"


class AcceptanceCommandError(RuntimeError):
    """Raised when an acceptance lifecycle command fails."""


def run_command(command: Sequence[str], *, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        list(command),
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AcceptanceCommandError(f"acceptance command failed with exit {completed.returncode}")
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


def validate_port(value: str) -> int:
    """Validate the externally exposed acceptance port before Compose starts."""
    try:
        port = int(value)
    except ValueError as error:
        raise ValueError("ACCEPTANCE_API_PORT must be a numeric port from 1 to 65535") from error
    if not 1 <= port <= 65535:
        raise ValueError("ACCEPTANCE_API_PORT must be a numeric port from 1 to 65535")
    return port


def parse_seed_result(output: str) -> dict[str, Any]:
    for line in reversed(output.splitlines()):
        if "|" in line:
            line = line.split("|", 1)[1].strip()
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and {"seed", "as_of", "fingerprint"}.issubset(value):
            return value
    raise AcceptanceCommandError("commerce seed did not produce its JSON result")


def _environment(port: str, password: str, token: str, acceptance_as_of: str) -> dict[str, str]:
    return {
        "ACCEPTANCE_DB_NAME": "commerce_acceptance",
        "ACCEPTANCE_DB_USER": "commerce_acceptance",
        "ACCEPTANCE_DB_PASSWORD": password,
        "ACCEPTANCE_API_PORT": port,
        "ACCEPTANCE_AS_OF": acceptance_as_of,
        "NOVACOMMERCE_DATABASE__URL": (
            "postgresql+asyncpg://commerce_acceptance:"
            f"{password}@commerce-postgres:5432/commerce_acceptance"
        ),
        "NOVACOMMERCE_SERVICE_TOKEN": token,
    }


def _run_level_as_of() -> str:
    configured = os.environ.get("ACCEPTANCE_AS_OF")
    if configured is not None:
        return serialize_acceptance_as_of(parse_acceptance_as_of(configured))
    return serialize_acceptance_as_of(datetime.now(UTC))


def run_acceptance() -> int:
    port = validate_port(os.environ.get("ACCEPTANCE_API_PORT", "18010"))
    password = secrets.token_urlsafe(32)
    token = secrets.token_urlsafe(32)
    acceptance_as_of = _run_level_as_of()
    project = f"novacommerce-acceptance-{uuid.uuid4().hex[:12]}"
    temp_path: Path | None = None
    env = os.environ.copy()
    env.update(
        {
            "ACCEPTANCE_BASE_URL": f"http://127.0.0.1:{port}",
            "ACCEPTANCE_SERVICE_TOKEN": token,
            "ACCEPTANCE_AS_OF": acceptance_as_of,
        }
    )
    primary_error: Exception | None = None
    teardown_errors: list[Exception] = []
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix="novacommerce-acceptance-",
            suffix=".env",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            with suppress(NotImplementedError, OSError):
                os.chmod(temp_path, stat.S_IRUSR | stat.S_IWUSR)
            for key, value in _environment(str(port), password, token, acceptance_as_of).items():
                temp_file.write(f"{key}={value}\n")
            temp_file.write(
                "ACCEPTANCE_SCENARIO_MANIFEST=/acceptance/novacommerce-scenarios.json\n"
            )

        run_command(
            compose_command(
                project,
                temp_path,
                "up",
                "-d",
                "--wait",
                "--wait-timeout",
                "120",
                "commerce-api",
            ),
            env=env,
        )
        seed_output = run_command(
            compose_command(project, temp_path, "logs", "--no-color", "commerce-seed"), env=env
        )
        seed_result = parse_seed_result(seed_output)
        expected = json.loads(MANIFEST.read_text(encoding="utf-8"))
        if any(
            seed_result.get(key) != expected.get(key)
            for key in ("seed", "as_of", "fingerprint", "scenario_ids")
        ):
            raise AcceptanceCommandError(
                "canonical seed result does not match the external manifest"
            )
        print(
            "Commerce acceptance seed verified: "
            + json.dumps(
                {
                    "seed": seed_result["seed"],
                    "as_of": seed_result["as_of"],
                    "counts": seed_result.get("counts", {}),
                    "fingerprint": seed_result["fingerprint"],
                },
                sort_keys=True,
            )
        )

        acceptance_env = env.copy()
        acceptance_env["ACCEPTANCE_SCENARIO_MANIFEST"] = str(MANIFEST)
        test_output = run_command(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/acceptance/commerce",
                "-m",
                "commerce_acceptance",
                "-q",
            ],
            env=acceptance_env,
        )
        summaries = [line.strip() for line in test_output.splitlines() if line.strip()]
        if summaries:
            print(f"Commerce acceptance HTTP suite: {summaries[-1]}")
    except Exception as error:
        primary_error = error

    if temp_path is not None:
        try:
            run_command(
                compose_command(project, temp_path, "down", "--volumes", "--remove-orphans"),
                env=env,
            )
        except Exception as error:  # pragma: no cover - exercised by lifecycle failure tests
            teardown_errors.append(error)
        try:
            temp_path.unlink(missing_ok=True)
        except OSError as error:  # pragma: no cover - filesystem failure
            teardown_errors.append(error)

    if primary_error is not None and teardown_errors:
        raise ExceptionGroup(
            "acceptance lifecycle and teardown failed", [primary_error, *teardown_errors]
        )
    if primary_error is not None:
        raise primary_error
    if teardown_errors:
        raise AcceptanceCommandError("acceptance teardown failed") from teardown_errors[0]
    return 0


def main() -> int:
    return run_acceptance()


if __name__ == "__main__":
    raise SystemExit(main())
