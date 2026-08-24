"""Run the permanent CommerceClient contract against Dockerized NovaCommerce."""

import json
import os
import secrets
import stat
import sys
import tempfile
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from scripts.acceptance_time import parse_acceptance_as_of, serialize_acceptance_as_of
from scripts.run_commerce_acceptance import (
    MANIFEST,
    AcceptanceCommandError,
    _environment,
    compose_command,
    parse_seed_result,
    run_command,
    validate_port,
)


def _run_level_as_of() -> str:
    configured = os.environ.get("ACCEPTANCE_AS_OF")
    if configured is not None:
        return serialize_acceptance_as_of(parse_acceptance_as_of(configured))
    return serialize_acceptance_as_of(datetime.now(UTC))


def run_contract() -> int:
    port = validate_port(os.environ.get("ACCEPTANCE_API_PORT", "18011"))
    password = secrets.token_urlsafe(32)
    token = secrets.token_urlsafe(32)
    acceptance_as_of = _run_level_as_of()
    project = f"novacommerce-client-contract-{uuid.uuid4().hex[:12]}"
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
            prefix="novacommerce-client-contract-",
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
            "Commerce client contract seed verified: "
            + json.dumps(
                {
                    "seed": seed_result["seed"],
                    "as_of": seed_result["as_of"],
                    "fingerprint": seed_result["fingerprint"],
                },
                sort_keys=True,
            )
        )

        contract_env = env.copy()
        contract_env["ACCEPTANCE_SCENARIO_MANIFEST"] = str(MANIFEST)
        test_output = run_command(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/integration/test_commerce_client_contract.py",
                "-m",
                "commerce_client_contract",
                "-q",
            ],
            env=contract_env,
        )
        summaries = [line.strip() for line in test_output.splitlines() if line.strip()]
        if summaries:
            print(f"CommerceClient contract suite: {summaries[-1]}")
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
            "CommerceClient contract lifecycle and teardown failed",
            [primary_error, *teardown_errors],
        )
    if primary_error is not None:
        raise primary_error
    if teardown_errors:
        raise AcceptanceCommandError(
            "CommerceClient contract teardown failed"
        ) from teardown_errors[0]
    return 0


if __name__ == "__main__":
    raise SystemExit(run_contract())
