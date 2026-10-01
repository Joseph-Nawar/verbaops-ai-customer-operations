"""Run M0 P0-P3 through the real public API using the selected DEV evidence gate."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
STACK_DIR = ROOT / "artifacts/m5d/stack"
STATE_FILE = STACK_DIR / "stack.json"
ENV_FILE = STACK_DIR / "local.env"
GATE_REPORT = ROOT / "artifacts/m5d/gate-calibration/gate-report.json"
API_BASE_URL = "http://127.0.0.1:8000"
GROUNDING_CANDIDATES = (
    "P0_CURRENT",
    "P1_PROMPT_V3",
    "P2_FAIL_CLOSED_CITATIONS",
    "P3_ONE_REPAIR_THEN_FAIL_CLOSED",
)
INTER_CASE_DELAY_SECONDS = 12.0


def _local_environment() -> tuple[dict[str, str], tuple[str, ...]]:
    values = {
        key: value
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines()
        if line and "=" in line
        for key, value in [line.split("=", 1)]
    }
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    environment = os.environ.copy()
    environment.update(
        {
            "VERBAOPS_ENVIRONMENT": "development",
            "VERBAOPS_DATABASE__URL": (
                f"postgresql+asyncpg://{values['VERBAOPS_DB_USER']}:{values['VERBAOPS_DB_PASSWORD']}"
                f"@127.0.0.1:{state['database_port']}/{values['VERBAOPS_DB_NAME']}"
            ),
            "VERBAOPS_REDIS__URL": f"redis://127.0.0.1:{state['redis_port']}/0",
            "VERBAOPS_LLM__BASE_URL": f"http://127.0.0.1:{state['gateway_port']}/v1",
            "VERBAOPS_LLM__API_KEY": values["LITELLM_MASTER_KEY"],
            "VERBAOPS_LLM__TIMEOUT_SECONDS": "60",
            "VERBAOPS_RAG__RERANKER_URL": f"http://127.0.0.1:{state['reranker_tei_port']}",
            "VERBAOPS_COMMERCE__BASE_URL": f"http://127.0.0.1:{state['commerce_api_port']}",
            "VERBAOPS_COMMERCE__SERVICE_TOKEN": values["NOVACOMMERCE_SERVICE_TOKEN"],
            "VERBAOPS_AUTH__DEVELOPMENT_TOKEN": values["VERBAOPS_AUTH__DEVELOPMENT_TOKEN"],
            "VERBAOPS_AUTH__DEVELOPMENT_PRINCIPAL_ID": values[
                "VERBAOPS_AUTH__DEVELOPMENT_PRINCIPAL_ID"
            ],
            "VERBAOPS_AUTH__DEVELOPMENT_TENANT_ID": values["VERBAOPS_AUTH__DEVELOPMENT_TENANT_ID"],
            "VERBAOPS_AUTH__DEVELOPMENT_CUSTOMER_ID": values[
                "VERBAOPS_AUTH__DEVELOPMENT_CUSTOMER_ID"
            ],
            "VERBAOPS_AGENT_API_URL": API_BASE_URL,
            "NOVACOMMERCE_SERVICE_TOKEN": values["NOVACOMMERCE_SERVICE_TOKEN"],
            "LITELLM_MASTER_KEY": values["LITELLM_MASTER_KEY"],
            "PYTHONUNBUFFERED": "1",
        }
    )
    hidden = {
        value
        for value in (
            os.environ.get("VERBAOPS_AGENT_FAST_API_KEY", ""),
            values["VERBAOPS_DB_PASSWORD"],
            values["COMMERCE_DB_PASSWORD"],
            values["NOVACOMMERCE_SERVICE_TOKEN"],
            values["VERBAOPS_AUTH__DEVELOPMENT_TOKEN"],
            values["LITELLM_MASTER_KEY"],
            environment["VERBAOPS_DATABASE__URL"],
        )
        if value
    }
    return environment, tuple(hidden)


def _wait_for_api(process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("M5D evaluation API exited during startup")
        try:
            with urlopen(f"{API_BASE_URL}/ready", timeout=2) as response:
                if response.status == 200:
                    return
        except (OSError, URLError):
            time.sleep(1)
    raise RuntimeError("M5D evaluation API did not become ready")


def _redact_diagnostics(value: str, hidden: tuple[str, ...]) -> str:
    for secret in hidden:
        value = value.replace(secret, "[redacted]")
    return " ".join(value.split())[-1200:]


def _assert_provider_secret_absent_from_artifacts_and_gateway_logs(
    provider_key: str, hidden: tuple[str, ...]
) -> None:
    for path in (ROOT / "artifacts/m5d").rglob("*"):
        if (
            path.is_file()
            and path.suffix in {".json", ".jsonl", ".md", ".log"}
            and provider_key
            and provider_key in path.read_text(encoding="utf-8", errors="replace")
        ):
            raise RuntimeError("provider credential was detected in an M5D artifact")
    logs = subprocess.run(
        ["docker", "logs", "verbaops-m5d-b-llm-gateway-1"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if provider_key and provider_key in (logs.stdout or "") + (logs.stderr or ""):
        raise RuntimeError("provider credential was detected in gateway logs")


def run_sweep() -> None:
    environment, hidden = _local_environment()
    provider_key = os.environ.get("VERBAOPS_AGENT_FAST_API_KEY", "")
    if not all(
        os.environ.get(name)
        for name in (
            "VERBAOPS_AGENT_FAST_MODEL",
            "VERBAOPS_AGENT_FAST_BASE_URL",
            "VERBAOPS_AGENT_FAST_API_KEY",
        )
    ):
        raise RuntimeError("agent-fast configuration became unavailable before DEV evaluation")
    if (
        os.environ["VERBAOPS_AGENT_FAST_MODEL"] != "groq/openai/gpt-oss-120b"
        or os.environ["VERBAOPS_AGENT_FAST_BASE_URL"] != "https://api.groq.com/openai/v1"
    ):
        raise RuntimeError("agent-fast route differs from the frozen M0 Stage 5 route")
    gate_report = json.loads(GATE_REPORT.read_text(encoding="utf-8"))
    selected = gate_report.get("selected_gate")
    if not isinstance(selected, dict) or gate_report.get("holdout_executed") is not False:
        raise RuntimeError("DEV gate report is missing or invalid")
    gate = str(selected["gate"])
    threshold = float(selected["threshold"])
    for candidate in GROUNDING_CANDIDATES:
        run_dir = ROOT / "artifacts/m5d/grounding" / candidate
        run_dir.mkdir(parents=True, exist_ok=True)
        checkpoint = run_dir / "grounded_cases.jsonl"
        completed_before_run = (
            len(checkpoint.read_text(encoding="utf-8").splitlines()) if checkpoint.exists() else 0
        )
        delayed_candidates = {"P2_FAIL_CLOSED_CITATIONS", "P3_ONE_REPAIR_THEN_FAIL_CLOSED"}
        delay_seconds = (
            INTER_CASE_DELAY_SECONDS
            if completed_before_run < 96 and candidate in delayed_candidates
            else 0.0
        )
        api_process = subprocess.Popen(
            [
                sys.executable,
                "scripts/run_m5d_api.py",
                "--gate",
                gate,
                "--threshold",
                str(threshold),
                "--grounding",
                candidate,
                "--model-candidate",
                "M0",
                "--port",
                "8000",
            ],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            _wait_for_api(api_process)
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/run_m5d_grounded_eval.py",
                    "--run-id",
                    f"m5d-b-dev-M0-{candidate}",
                    "--run-dir",
                    str(run_dir),
                    "--gate-report",
                    str(GATE_REPORT),
                    "--gate",
                    gate,
                    "--threshold",
                    str(threshold),
                    "--grounding",
                    candidate,
                    "--model-candidate",
                    "M0",
                    "--inter-case-delay-seconds",
                    str(delay_seconds),
                    "--split",
                    "dev",
                ],
                cwd=ROOT,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=1800,
            )
            if result.returncode:
                raise RuntimeError(
                    f"{candidate} run stopped with exit {result.returncode}: "
                    + _redact_diagnostics(result.stdout + " " + result.stderr, hidden)
                )
            print(_redact_diagnostics(result.stdout, hidden))
            _assert_provider_secret_absent_from_artifacts_and_gateway_logs(provider_key, hidden)
        finally:
            api_process.terminate()
            try:
                api_process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                api_process.kill()
                api_process.wait(timeout=5)


if __name__ == "__main__":
    try:
        run_sweep()
    except (OSError, subprocess.SubprocessError, RuntimeError, KeyError, ValueError) as error:
        raise SystemExit(
            f"M5D grounded DEV sweep stopped safely ({type(error).__name__})"
        ) from None
