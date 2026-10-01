"""Create or resume the isolated M5D-B DEV service stack."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STACK_DIR = ROOT / "artifacts/m5d/stack"
ENV_FILE = STACK_DIR / "local.env"
STATE_FILE = STACK_DIR / "stack.json"
COMPOSE_FILE = ROOT / "docker-compose.m5d-b-eval.yml"
EXPECTED_MODEL = "groq/openai/gpt-oss-120b"
EXPECTED_BASE_URL = "https://api.groq.com/openai/v1"
PROVIDER_VARIABLES = (
    "VERBAOPS_AGENT_FAST_MODEL",
    "VERBAOPS_AGENT_FAST_BASE_URL",
    "VERBAOPS_AGENT_FAST_API_KEY",
)


def _provider_presence() -> None:
    missing = [name for name in PROVIDER_VARIABLES if not os.environ.get(name)]
    if missing:
        raise RuntimeError("missing provider variables: " + ", ".join(missing))
    model = os.environ["VERBAOPS_AGENT_FAST_MODEL"]
    base_url = os.environ["VERBAOPS_AGENT_FAST_BASE_URL"]
    if model != EXPECTED_MODEL or base_url != EXPECTED_BASE_URL:
        raise RuntimeError("agent-fast route differs from the reviewed Stage 4 M0 route")
    print(f"MODEL={model}")
    print(f"BASE_URL={base_url}")
    print("API_KEY=PRESENT")


def _write_environment() -> None:
    STACK_DIR.mkdir(parents=True, exist_ok=True)
    if ENV_FILE.exists():
        return
    verbaops_password = secrets.token_urlsafe(30)
    commerce_password = secrets.token_urlsafe(30)
    commerce_token = secrets.token_urlsafe(30)
    dev_token = secrets.token_urlsafe(30)
    gateway_key = secrets.token_urlsafe(30)
    tenant_id = "10000000-0000-0000-0000-000000000002"
    values = {
        "VERBAOPS_DB_NAME": "verbaops_m5d_dev",
        "VERBAOPS_DB_USER": "verbaops_m5d_dev",
        "VERBAOPS_DB_PASSWORD": verbaops_password,
        "VERBAOPS_DB_PORT": "0",
        "VERBAOPS_DATABASE__URL": (
            "postgresql+asyncpg://verbaops_m5d_dev:"
            f"{verbaops_password}@verbaops-postgres:5432/verbaops_m5d_dev"
        ),
        "COMMERCE_DB_NAME": "novacommerce_m5d_dev",
        "COMMERCE_DB_USER": "novacommerce_m5d_dev",
        "COMMERCE_DB_PASSWORD": commerce_password,
        "COMMERCE_DB_PORT": "0",
        "NOVACOMMERCE_DATABASE__URL": (
            "postgresql+asyncpg://novacommerce_m5d_dev:"
            f"{commerce_password}@commerce-postgres:5432/novacommerce_m5d_dev"
        ),
        "NOVACOMMERCE_SERVICE_TOKEN": commerce_token,
        "COMMERCE_API_HOST_PORT": "0",
        "VERBAOPS_AUTH__DEVELOPMENT_TOKEN": dev_token,
        "VERBAOPS_AUTH__DEVELOPMENT_PRINCIPAL_ID": "10000000-0000-0000-0000-000000000001",
        "VERBAOPS_AUTH__DEVELOPMENT_TENANT_ID": tenant_id,
        "VERBAOPS_AUTH__DEVELOPMENT_CUSTOMER_ID": "d77809e8-6d3b-5792-9128-ff2bc88bc955",
        "LITELLM_MASTER_KEY": gateway_key,
        "M5D_REDIS_HOST_PORT": "0",
        "M5D_GATEWAY_HOST_PORT": "0",
        "TEI_EMBEDDING_HOST_PORT": "0",
        "TEI_RERANKER_HOST_PORT": "0",
        "VERBAOPS_EMBEDDING_MULTILINGUAL_MODEL": "openai/intfloat/multilingual-e5-base",
        "VERBAOPS_EMBEDDING_MULTILINGUAL_BASE_URL": "http://tei-embedding:80/v1",
        "VERBAOPS_EMBEDDING_MULTILINGUAL_API_KEY": "local-m5d-embedding-key",
    }
    ENV_FILE.write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8"
    )


def _compose_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def _compose(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "docker",
            "compose",
            "--project-name",
            "verbaops-m5d-b",
            "--env-file",
            str(ENV_FILE),
            "-f",
            str(COMPOSE_FILE),
            *arguments,
        ],
        cwd=ROOT,
        env=os.environ.copy(),
        check=False,
        capture_output=True,
        text=True,
        timeout=1800,
    )


def _host_port(service: str, container_port: int) -> int:
    result = _compose("port", service, str(container_port))
    if result.returncode:
        raise RuntimeError(f"could not resolve local {service} port")
    last = result.stdout.strip().splitlines()[-1]
    try:
        return int(last.rsplit(":", 1)[1])
    except (IndexError, ValueError):
        raise RuntimeError(f"could not parse local {service} port") from None


def _required_services_healthy() -> bool:
    result = _compose("ps", "--format", "json")
    if result.returncode:
        return False
    try:
        services = {
            str(item["Service"]): item
            for line in result.stdout.splitlines()
            if line.strip()
            for item in [json.loads(line)]
        }
    except (json.JSONDecodeError, KeyError, TypeError):
        return False
    required = {
        "redis",
        "verbaops-postgres",
        "commerce-api",
        "llm-gateway",
        "tei-embedding",
        "tei-reranker",
    }
    return all(
        service in services
        and services[service].get("State") == "running"
        and services[service].get("Health") == "healthy"
        for service in required
    )


def _ensure_redis_service() -> None:
    result = _compose(
        "up",
        "-d",
        "--wait",
        "--wait-timeout",
        "1200",
        "redis",
    )
    if result.returncode:
        raise RuntimeError("M5D isolated Redis startup failed: " + _safe_error(result))


def _safe_error(result: subprocess.CompletedProcess[str]) -> str:
    message = f"{result.stdout}\n{result.stderr}"
    for variable in PROVIDER_VARIABLES:
        value = os.environ.get(variable, "")
        if value:
            message = message.replace(value, "[redacted]")
    for value in _compose_env().values():
        if value and len(value) > 20:
            message = message.replace(value, "[redacted]")
    return " ".join(message.split())[-1500:]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--down", action="store_true", help="stop the isolated services")
    args = parser.parse_args()
    if args.down:
        if ENV_FILE.exists():
            result = _compose("down", "--remove-orphans")
            if result.returncode:
                raise RuntimeError("M5D stack shutdown failed: " + _safe_error(result))
            print("M5D isolated services stopped; local DB volumes preserved for resume.")
        return

    _provider_presence()
    if not COMPOSE_FILE.is_file():
        raise RuntimeError("M5D evaluation Compose definition is missing")
    _write_environment()
    _ensure_redis_service()
    if not _required_services_healthy():
        result = _compose(
            "up",
            "-d",
            "--wait",
            "--wait-timeout",
            "1200",
            "verbaops-postgres",
            "redis",
            "verbaops-migrate",
            "commerce-api",
            "llm-gateway",
            "tei-reranker",
        )
        if result.returncode:
            raise RuntimeError("M5D isolated stack startup failed: " + _safe_error(result))
    state = {
        "project": "verbaops-m5d-b",
        "database_port": _host_port("verbaops-postgres", 5432),
        "redis_port": _host_port("redis", 6379),
        "commerce_api_port": _host_port("commerce-api", 8000),
        "gateway_port": _host_port("llm-gateway", 4000),
        "embedding_tei_port": _host_port("tei-embedding", 80),
        "reranker_tei_port": _host_port("tei-reranker", 80),
        "agent_fast_model": os.environ["VERBAOPS_AGENT_FAST_MODEL"],
        "agent_fast_base_url": os.environ["VERBAOPS_AGENT_FAST_BASE_URL"],
        "api_key": "PRESENT",
    }
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "stack": "ready",
                "database_port": state["database_port"],
                "commerce_api_port": state["commerce_api_port"],
                "gateway_url": f"http://127.0.0.1:{state['gateway_port']}/v1",
                "embedding_tei_port": state["embedding_tei_port"],
                "reranker_tei_port": state["reranker_tei_port"],
                "credential_state": "PRESENT",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except (OSError, subprocess.SubprocessError, RuntimeError) as error:
        raise SystemExit(str(error)) from None
