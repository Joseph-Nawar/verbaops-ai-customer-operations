"""Run a genuine Stage 4 baseline through the public VerbaOps API."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import tempfile
import uuid
from collections.abc import Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from verbaops.agent.versions import GRAPH_VERSION, PROMPT_VERSION, TOOL_SCHEMA_VERSION
from verbaops.evaluation.baseline import (
    EXPECTED_DATASET_SHA256,
    BaselineArtifact,
    build_baseline_artifact,
    write_baseline_artifacts,
)
from verbaops.evaluation.cases import load_cases
from verbaops.evaluation.corpus import CorpusManifest
from verbaops.evaluation.errors import ProviderQuotaExceeded
from verbaops.evaluation.live import LiveEvaluationAdapter, TraceReader, assert_live_corpus_contract
from verbaops.evaluation.models import EvaluationSummary
from verbaops.evaluation.repository import EvaluationRepository
from verbaops.evaluation.runner import run_evaluation

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "docker-compose.agent-live.yml"
CONFIG_FILE = ROOT / "infra/litellm/config.yaml"
CASES_FILE = ROOT / "evals/agent/v0.1/cases.jsonl"
MANIFEST_FILE = ROOT / "evals/agent/v0.1/manifest.json"
SCENARIO_FILE = ROOT / "tests/acceptance/fixtures/novacommerce-scenarios.json"
BASELINE_JSON = ROOT / "evals/baselines/stage4-agent-v0.1-baseline.json"
BASELINE_MARKDOWN = ROOT / "evals/baselines/stage4-agent-v0.1-baseline.md"
RESUME_STATE_FILE = ROOT / ".stage4-agent-v0.1-resume.json"
REQUIRED_PROVIDER_VARIABLES = (
    "VERBAOPS_AGENT_FAST_MODEL",
    "VERBAOPS_AGENT_FAST_BASE_URL",
    "VERBAOPS_AGENT_FAST_API_KEY",
)


class LiveEvaluationError(RuntimeError):
    """Raised when the disposable genuine-evaluation lifecycle is unsafe."""


def missing_provider_variables(environment: dict[str, str] | None = None) -> tuple[str, ...]:
    """Return missing names without reading or exposing their values."""

    values = os.environ if environment is None else environment
    return tuple(name for name in REQUIRED_PROVIDER_VARIABLES if not values.get(name))


def _redact(value: str, secrets_to_hide: Sequence[str]) -> str:
    redacted = value
    for secret in secrets_to_hide:
        if secret:
            redacted = redacted.replace(secret, "[redacted]")
    return re.sub(r"(?i)(authorization:\s*bearer\s+)[^\s;]+", r"\1[redacted]", redacted)[-4000:]


def run_command(
    command: Sequence[str], *, environment: dict[str, str], secrets_to_hide: Sequence[str]
) -> str:
    completed = subprocess.run(
        list(command),
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        diagnostics = _redact(f"{completed.stdout}\n{completed.stderr}", secrets_to_hide).strip()
        suffix = f": {diagnostics}" if diagnostics else ""
        raise LiveEvaluationError(
            f"live evaluation command failed with exit {completed.returncode}{suffix}"
        )
    return completed.stdout


def compose_command(project: str, env_file: Path, *arguments: str) -> list[str]:
    """Build the disposable stack command using the real deployment LiteLLM config."""

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


def select_smoke_cases(cases: tuple[Any, ...]) -> tuple[Any, ...]:
    """Select five representative cases without changing the approved corpus."""

    categories = (
        "order-status",
        "missing-ambiguous-identifiers",
        "unsupported-write",
        "safety-injection-identity-cross-customer",
        "benign-no-tool",
    )
    selected = []
    for category in categories:
        selected.append(next(case for case in cases if case.category == category))
    return tuple(selected)


def _compose_port(output: str, service: str) -> int:
    match = re.search(r":(\d+)\s*$", output.strip())
    if match is None:
        raise LiveEvaluationError(f"Docker did not report the {service} port")
    return int(match.group(1))


def _seed_result(output: str) -> dict[str, Any]:
    for line in reversed(output.splitlines()):
        try:
            value = json.loads(line.split("|", 1)[-1].strip())
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and {"seed", "fingerprint", "scenario_ids"}.issubset(value):
            return value
    raise LiveEvaluationError("canonical Commerce seed did not produce its manifest result")


def _compose_environment() -> tuple[dict[str, str], list[str]]:
    verbaops_password = secrets.token_urlsafe(32)
    commerce_password = secrets.token_urlsafe(32)
    commerce_token = secrets.token_urlsafe(32)
    development_token = secrets.token_urlsafe(32)
    gateway_key = secrets.token_urlsafe(32)
    principal_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    generated = {
        "VERBAOPS_DB_NAME": "verbaops_live_eval",
        "VERBAOPS_DB_USER": "verbaops_live_eval",
        "VERBAOPS_DB_PASSWORD": verbaops_password,
        "VERBAOPS_DB_PORT": "0",
        "VERBAOPS_DATABASE__URL": (
            "postgresql+asyncpg://verbaops_live_eval:"
            f"{verbaops_password}@verbaops-postgres:5432/verbaops_live_eval"
        ),
        "COMMERCE_DB_NAME": "commerce_live_eval",
        "COMMERCE_DB_USER": "commerce_live_eval",
        "COMMERCE_DB_PASSWORD": commerce_password,
        "NOVACOMMERCE_DATABASE__URL": (
            "postgresql+asyncpg://commerce_live_eval:"
            f"{commerce_password}@commerce-postgres:5432/commerce_live_eval"
        ),
        "NOVACOMMERCE_SERVICE_TOKEN": commerce_token,
        "VERBAOPS_AUTH__DEVELOPMENT_TOKEN": development_token,
        "VERBAOPS_AUTH__DEVELOPMENT_PRINCIPAL_ID": principal_id,
        "VERBAOPS_AUTH__DEVELOPMENT_TENANT_ID": tenant_id,
        "VERBAOPS_AUTH__DEVELOPMENT_CUSTOMER_ID": "d77809e8-6d3b-5792-9128-ff2bc88bc955",
        "LITELLM_MASTER_KEY": gateway_key,
        "AGENT_LIVE_API_PORT": "0",
        "AGENT_LIVE_GATEWAY_PORT": "0",
        # LiteLLM v1.98.0 parses every model entry at startup. These aliases
        # are intentionally inert and are never selected by the locked agent.
        "VERBAOPS_AGENT_REASONING_MODEL": "openai/unused-agent-reasoning",
        "VERBAOPS_AGENT_REASONING_BASE_URL": "http://127.0.0.1:9/v1",
        "VERBAOPS_AGENT_REASONING_API_KEY": "unused",
        "VERBAOPS_EVAL_JUDGE_MODEL": "openai/unused-eval-judge",
        "VERBAOPS_EVAL_JUDGE_BASE_URL": "http://127.0.0.1:9/v1",
        "VERBAOPS_EVAL_JUDGE_API_KEY": "unused",
        "VERBAOPS_EMBEDDING_MULTILINGUAL_MODEL": "openai/unused-embedding",
        "VERBAOPS_EMBEDDING_MULTILINGUAL_BASE_URL": "http://127.0.0.1:9/v1",
        "VERBAOPS_EMBEDDING_MULTILINGUAL_API_KEY": "unused",
    }
    hidden = [
        *generated.values(),
        *(os.environ.get(name, "") for name in REQUIRED_PROVIDER_VARIABLES),
    ]
    return generated, [value for value in hidden if value]


def _compose_process_environment() -> dict[str, str]:
    environment = os.environ.copy()
    keep = set(REQUIRED_PROVIDER_VARIABLES)
    for key in list(environment):
        if (
            key.startswith(("VERBAOPS_", "NOVACOMMERCE_", "AGENT_LIVE_", "LITELLM_MASTER_KEY"))
            and key not in keep
        ):
            environment.pop(key)
    return environment


def _write_env_file(values: dict[str, str]) -> Path:
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", prefix="verbaops-live-eval-", suffix=".env", delete=False
    ) as handle:
        path = Path(handle.name)
        with suppress(NotImplementedError, OSError):
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        for key, value in values.items():
            handle.write(f"{key}={value}\n")
    return path


def _provider_config_fingerprint(environment: Mapping[str, str] | None = None) -> str:
    """Hash only non-secret provider routing inputs for resume consistency."""

    values = os.environ if environment is None else environment
    model = values.get("VERBAOPS_AGENT_FAST_MODEL", "")
    base_url = values.get("VERBAOPS_AGENT_FAST_BASE_URL", "")
    return hashlib.sha256(f"{model}\0{base_url}".encode()).hexdigest()


def build_resume_state(
    *,
    project: str,
    env_file: Path,
    run_id: str,
    execution_sha: str,
    environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build local control state without serializing provider credentials."""

    return {
        "project": project,
        "env_file": str(env_file),
        "run_id": run_id,
        "execution_sha": execution_sha,
        "provider_config_fingerprint": _provider_config_fingerprint(environment),
    }


def _read_env_file(path: Path) -> dict[str, str]:
    """Read only the generated non-provider compose environment file."""

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def _load_resume_state() -> dict[str, str] | None:
    if not RESUME_STATE_FILE.is_file():
        return None
    raw = json.loads(RESUME_STATE_FILE.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not all(
        isinstance(raw.get(key), str)
        for key in (
            "project",
            "env_file",
            "run_id",
            "execution_sha",
            "provider_config_fingerprint",
        )
    ):
        raise LiveEvaluationError("baseline resume state is invalid")
    return raw


def _load_corpus() -> tuple[CorpusManifest, tuple[Any, ...], dict[str, Any]]:
    manifest = CorpusManifest.model_validate(json.loads(MANIFEST_FILE.read_text(encoding="utf-8")))
    cases = load_cases(CASES_FILE)
    scenario_manifest = json.loads(SCENARIO_FILE.read_text(encoding="utf-8"))
    assert_live_corpus_contract(cases)
    return manifest, cases, scenario_manifest


def baseline_persistence_is_complete(
    *,
    persisted_status: str,
    persisted_dataset_sha256: str,
    persisted_capability_alias: str,
    result_count: int,
    expected_case_count: int,
    summary: EvaluationSummary,
) -> bool:
    """Validate baseline completeness without requiring optional provider metadata."""

    return bool(
        persisted_status == "completed"
        and result_count == expected_case_count
        and persisted_dataset_sha256 == EXPECTED_DATASET_SHA256
        and persisted_capability_alias == "agent-fast"
        and summary.case_count == expected_case_count
        and summary.capability_alias == "agent-fast"
        and summary.gateway_model_id is not None
        and summary.model is not None
    )


async def _run_smoke(
    base_url: str,
    token: str,
    database_url: str,
    cases: tuple[Any, ...],
    secret_values: tuple[str, ...],
) -> None:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    reader = TraceReader(session_factory)
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=60) as client:
            adapter = LiveEvaluationAdapter(
                base_url, token, reader, client, secret_values=secret_values
            )
            for case in select_smoke_cases(cases):
                observation = await adapter.observe(case)
                if observation.capability_alias != "agent-fast":
                    raise LiveEvaluationError("smoke did not record capability alias agent-fast")
                if observation.capability_alias == "deterministic-fixture":
                    raise LiveEvaluationError("smoke unexpectedly used deterministic-fixture")
                if observation.agent_run_id is None:
                    raise LiveEvaluationError("smoke did not collect a persisted agent trace")
    finally:
        await engine.dispose()


async def _run_baseline(
    base_url: str,
    token: str,
    database_url: str,
    manifest: CorpusManifest,
    cases: tuple[Any, ...],
    scenario_manifest: dict[str, Any],
    run_id: uuid.UUID,
    execution_sha: str,
    output_root: Path,
    secret_values: tuple[str, ...],
) -> BaselineArtifact:
    engine: AsyncEngine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    started_at = datetime.now(UTC)
    metadata = {
        "id": run_id,
        "dataset_version": manifest.dataset_version,
        "dataset_sha256": EXPECTED_DATASET_SHA256,
        "git_sha": execution_sha,
        "environment": "local-live",
        "capability_alias": "agent-fast",
        "prompt_version": PROMPT_VERSION,
        "graph_version": GRAPH_VERSION,
        "tool_schema_version": TOOL_SCHEMA_VERSION,
        "case_count": len(cases),
        "started_at": started_at,
    }
    from verbaops.evaluation.models import EvaluationRunMetadata

    try:
        reader = TraceReader(session_factory)
        async with (
            httpx.AsyncClient(base_url=base_url, timeout=60) as client,
            session_factory() as session,
        ):
            summary = await run_evaluation(
                cases,
                LiveEvaluationAdapter(base_url, token, reader, client, secret_values=secret_values),
                manifest=manifest,
                scenario_manifest=scenario_manifest,
                dataset_bytes=CASES_FILE.read_bytes(),
                output_root=output_root,
                run_id=run_id,
                metadata=EvaluationRunMetadata.model_validate(metadata),
                repository=EvaluationRepository(),
                session=session,
            )
        async with session_factory() as session:
            repository = EvaluationRepository()
            persisted_run = await repository.get_run(session, run_id)
            results = await repository.list_results(session, run_id)
        if not baseline_persistence_is_complete(
            persisted_status=persisted_run.status,
            persisted_dataset_sha256=persisted_run.dataset_sha256,
            persisted_capability_alias=persisted_run.capability_alias,
            result_count=len(results),
            expected_case_count=len(cases),
            summary=summary,
        ):
            raise LiveEvaluationError("baseline persistence did not contain exactly 120 results")
        if len({result.case_id for result in results}) != len(cases):
            raise LiveEvaluationError("baseline persistence contains duplicate case IDs")
        artifact = build_baseline_artifact(summary, results, execution_sha, datetime.now(UTC))
        write_baseline_artifacts(
            artifact,
            BASELINE_JSON,
            BASELINE_MARKDOWN,
            secret_values=secret_values,
        )
        return artifact
    finally:
        await engine.dispose()


def run_managed(mode: str) -> int:
    missing = missing_provider_variables()
    if missing:
        print("Missing required provider variables: " + ", ".join(missing))
        return 2
    if not CONFIG_FILE.is_file() or CONFIG_FILE.name != "config.yaml":
        raise LiveEvaluationError("real LiteLLM deployment config is unavailable")
    if mode == "baseline" and (BASELINE_JSON.exists() or BASELINE_MARKDOWN.exists()):
        raise LiveEvaluationError("the first genuine baseline artifact already exists")

    manifest, cases, scenario_manifest = _load_corpus()
    resume_state = _load_resume_state() if mode == "baseline" else None
    if resume_state is not None:
        if resume_state["provider_config_fingerprint"] != _provider_config_fingerprint():
            raise LiveEvaluationError("provider configuration changed during baseline resume")
        if (
            resume_state["execution_sha"]
            != run_command(
                ["git", "rev-parse", "HEAD"],
                environment=_compose_process_environment(),
                secrets_to_hide=(),
            ).strip()
        ):
            raise LiveEvaluationError("execution code changed during baseline resume")
        env_file = Path(resume_state["env_file"])
        if not env_file.is_file():
            raise LiveEvaluationError("baseline resume environment is unavailable")
        generated = _read_env_file(env_file)
        project = resume_state["project"]
        resume_run_id = uuid.UUID(resume_state["run_id"])
    else:
        generated, _ = _compose_environment()
        env_file = _write_env_file(generated)
        project = f"verbaops-agent-live-{uuid.uuid4().hex[:12]}"
        resume_run_id = None
    hidden = [
        *generated.values(),
        *(os.environ.get(name, "") for name in REQUIRED_PROVIDER_VARIABLES),
    ]
    process_environment = _compose_process_environment()
    primary_error: Exception | None = None
    result_code = 0
    try:
        run_command(
            compose_command(
                project, env_file, "up", "-d", "--wait", "--wait-timeout", "240", "verbaops-api"
            ),
            environment=process_environment,
            secrets_to_hide=hidden,
        )
        seed = _seed_result(
            run_command(
                compose_command(project, env_file, "logs", "--no-color", "commerce-seed"),
                environment=process_environment,
                secrets_to_hide=hidden,
            )
        )
        expected_seed = json.loads(SCENARIO_FILE.read_text(encoding="utf-8"))
        if any(
            seed.get(key) != expected_seed.get(key)
            for key in ("seed", "fingerprint", "scenario_ids")
        ):
            raise LiveEvaluationError("canonical Commerce seed does not match the stable manifest")
        api_port = _compose_port(
            run_command(
                compose_command(project, env_file, "port", "verbaops-api", "8000"),
                environment=process_environment,
                secrets_to_hide=hidden,
            ),
            "VerbaOps API",
        )
        db_port = _compose_port(
            run_command(
                compose_command(project, env_file, "port", "verbaops-postgres", "5432"),
                environment=process_environment,
                secrets_to_hide=hidden,
            ),
            "VerbaOps database",
        )
        base_url = f"http://127.0.0.1:{api_port}"
        database_url = (
            "postgresql+asyncpg://verbaops_live_eval:"
            f"{generated['VERBAOPS_DB_PASSWORD']}@127.0.0.1:{db_port}/verbaops_live_eval"
        )
        if resume_state is None:
            asyncio.run(
                _run_smoke(
                    base_url,
                    generated["VERBAOPS_AUTH__DEVELOPMENT_TOKEN"],
                    database_url,
                    cases,
                    tuple(hidden),
                )
            )
            print("Live smoke: 5 cases, genuine provider trace metadata verified; not a baseline.")
        else:
            print("Resuming the interrupted genuine baseline; pre-baseline smoke already passed.")
        if mode == "smoke":
            return 0
        execution_sha = (
            resume_state["execution_sha"]
            if resume_state is not None
            else run_command(
                ["git", "rev-parse", "HEAD"],
                environment=process_environment,
                secrets_to_hide=hidden,
            ).strip()
        )
        run_id = resume_run_id or uuid.uuid4()
        if resume_state is None:
            RESUME_STATE_FILE.write_text(
                json.dumps(
                    build_resume_state(
                        project=project,
                        env_file=env_file,
                        run_id=str(run_id),
                        execution_sha=execution_sha,
                        environment=process_environment,
                    ),
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        with tempfile.TemporaryDirectory(prefix="verbaops-live-artifacts-") as artifact_directory:
            artifact = asyncio.run(
                _run_baseline(
                    base_url,
                    generated["VERBAOPS_AUTH__DEVELOPMENT_TOKEN"],
                    database_url,
                    manifest,
                    cases,
                    scenario_manifest,
                    run_id,
                    execution_sha,
                    Path(artifact_directory),
                    tuple(hidden),
                )
            )
        print(
            f"Genuine baseline recorded: {artifact.case_count} cases, "
            f"unauthorized={artifact.unauthorized_action_count}, "
            f"critical_safety={artifact.critical_safety_violation_count}"
        )
        if artifact.unauthorized_action_count or artifact.critical_safety_violation_count:
            print("Safety evidence was preserved; Stage 4 is not locked.")
            return 3
        return 0
    except Exception as error:
        primary_error = error
    finally:
        teardown_error: Exception | None = None
        preserve_resume = isinstance(primary_error, ProviderQuotaExceeded)
        try:
            teardown_arguments = ["down", "--remove-orphans"]
            if not preserve_resume:
                teardown_arguments.insert(1, "--volumes")
            run_command(
                compose_command(project, env_file, *teardown_arguments),
                environment=process_environment,
                secrets_to_hide=hidden,
            )
        except Exception as error:
            teardown_error = error
        if not preserve_resume:
            env_file.unlink(missing_ok=True)
            RESUME_STATE_FILE.unlink(missing_ok=True)
        if primary_error is None and teardown_error is not None:
            primary_error = LiveEvaluationError("live evaluation teardown failed")
        if primary_error is not None and not isinstance(primary_error, ProviderQuotaExceeded):
            raise primary_error
        if isinstance(primary_error, ProviderQuotaExceeded):
            print(
                "Baseline interrupted by provider quota: "
                f"run_id={primary_error.run_id}, "
                f"completed={primary_error.completed_case_count}, "
                f"remaining={primary_error.remaining_case_count}"
            )
            result_code = 4
    return result_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--smoke", action="store_true")
    group.add_argument("--baseline", action="store_true")
    args = parser.parse_args()
    return run_managed("smoke" if args.smoke else "baseline")


if __name__ == "__main__":
    raise SystemExit(main())
