"""Run the permanent black-box NovaCommerce acceptance gate."""

import json
import os
import secrets
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

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


def _environment(port: str, password: str, token: str) -> dict[str, str]:
    return {
        "ACCEPTANCE_DB_NAME": "commerce_acceptance",
        "ACCEPTANCE_DB_USER": "commerce_acceptance",
        "ACCEPTANCE_DB_PASSWORD": password,
        "ACCEPTANCE_API_PORT": port,
        "NOVACOMMERCE_DATABASE__URL": (
            "postgresql+asyncpg://commerce_acceptance:"
            f"{password}@commerce-postgres:5432/commerce_acceptance"
        ),
        "NOVACOMMERCE_SERVICE_TOKEN": token,
    }


def main() -> int:
    port = os.environ.get("ACCEPTANCE_API_PORT", "18010")
    password = secrets.token_urlsafe(32)
    token = secrets.token_urlsafe(32)
    project = f"novacommerce-acceptance-{uuid.uuid4().hex[:12]}"
    temp_path: Path | None = None
    env = os.environ.copy()
    env.update(
        {"ACCEPTANCE_BASE_URL": f"http://127.0.0.1:{port}", "ACCEPTANCE_SERVICE_TOKEN": token}
    )
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix="novacommerce-acceptance-",
            suffix=".env",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            for key, value in _environment(port, password, token).items():
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
        return 0
    finally:
        teardown_error: Exception | None = None
        if temp_path is not None:
            try:
                run_command(
                    compose_command(project, temp_path, "down", "--volumes", "--remove-orphans"),
                    env=env,
                )
            except Exception as error:  # pragma: no cover - exercised by lifecycle failure tests
                teardown_error = error
            try:
                temp_path.unlink(missing_ok=True)
            except OSError as error:  # pragma: no cover - filesystem failure
                teardown_error = teardown_error or error
        if teardown_error is not None:
            raise AcceptanceCommandError("acceptance teardown failed") from teardown_error


if __name__ == "__main__":
    raise SystemExit(main())
