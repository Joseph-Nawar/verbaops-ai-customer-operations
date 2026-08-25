"""Run a genuine Stage 4 baseline through the public VerbaOps API."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import secrets
import stat
import subprocess
import tempfile
import uuid
from collections.abc import Sequence
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
from verbaops.evaluation.live import LiveEvaluationAdapter, TraceReader, assert_live_corpus_contract
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


def _load_corpus() -> tuple[CorpusManifest, tuple[Any, ...], dict[str, Any]]:
    manifest = CorpusManifest.model_validate(json.loads(MANIFEST_FILE.read_text(encoding="utf-8")))
    cases = load_cases(CASES_FILE)
    scenario_manifest = json.loads(SCENARIO_FILE.read_text(encoding="utf-8"))
    assert_live_corpus_contract(cases)
    return manifest, cases, scenario_manifest


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
    execution_sha: str,
    output_root: Path,
    secret_values: tuple[str, ...],
) -> BaselineArtifact:
    engine: AsyncEngine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    run_id = uuid.uuid4()
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
        if (
            persisted_run.status != "completed"
            or len(results) != len(cases)
            or persisted_run.dataset_sha256 != EXPECTED_DATASET_SHA256
            or persisted_run.capability_alias != "agent-fast"
            or summary.capability_alias != "agent-fast"
            or summary.gateway_model_id is None
            or summary.model is None
            or summary.provider is None
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
    generated, hidden = _compose_environment()
    env_file = _write_env_file(generated)
    process_environment = _compose_process_environment()
    project = f"verbaops-agent-live-{uuid.uuid4().hex[:12]}"
    primary_error: Exception | None = None
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
        if mode == "smoke":
            return 0
        execution_sha = run_command(
            ["git", "rev-parse", "HEAD"], environment=process_environment, secrets_to_hide=hidden
        ).strip()
        with tempfile.TemporaryDirectory(prefix="verbaops-live-artifacts-") as artifact_directory:
            artifact = asyncio.run(
                _run_baseline(
                    base_url,
                    generated["VERBAOPS_AUTH__DEVELOPMENT_TOKEN"],
                    database_url,
                    manifest,
                    cases,
                    scenario_manifest,
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
        try:
            run_command(
                compose_command(project, env_file, "down", "--volumes", "--remove-orphans"),
                environment=process_environment,
                secrets_to_hide=hidden,
            )
        except Exception as error:
            teardown_error = error
        env_file.unlink(missing_ok=True)
        if primary_error is None and teardown_error is not None:
            primary_error = LiveEvaluationError("live evaluation teardown failed")
        if primary_error is not None:
            raise primary_error
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--smoke", action="store_true")
    group.add_argument("--baseline", action="store_true")
    args = parser.parse_args()
    return run_managed("smoke" if args.smoke else "baseline")


if __name__ == "__main__":
    raise SystemExit(main())
