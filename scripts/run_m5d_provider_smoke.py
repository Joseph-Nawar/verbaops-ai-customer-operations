"""Run and save one sanitized real M0 agent-fast gateway smoke."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

STACK_ENV = ROOT / "artifacts/m5d/stack/local.env"
STACK_STATE = ROOT / "artifacts/m5d/stack/stack.json"
SMOKE_FILE = ROOT / "artifacts/m5d/provider-smoke.json"


def _read_local_stack() -> tuple[dict[str, str], dict[str, object]]:
    values = {
        key: value
        for line in STACK_ENV.read_text(encoding="utf-8").splitlines()
        if line and "=" in line
        for key, value in [line.split("=", 1)]
    }
    state = json.loads(STACK_STATE.read_text(encoding="utf-8"))
    return values, state


async def _run() -> dict[str, object]:
    from scripts.smoke_m5d_agent_fast import _smoke

    values, state = _read_local_stack()
    gateway_url = f"http://127.0.0.1:{state['gateway_port']}/v1"
    result = await _smoke(gateway_url, values["LITELLM_MASTER_KEY"])
    output = json.dumps(result, indent=2, sort_keys=True) + "\n"
    provider_key = os.environ.get("VERBAOPS_AGENT_FAST_API_KEY", "")
    if provider_key and provider_key in output:
        raise RuntimeError("provider credential detected in sanitized smoke data")
    logs = subprocess.run(
        ["docker", "logs", "verbaops-m5d-b-llm-gateway-1"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if provider_key and provider_key in (logs.stdout or "") + (logs.stderr or ""):
        raise RuntimeError("provider credential detected in gateway logs")
    SMOKE_FILE.write_text(output, encoding="utf-8")
    result["provider_key_absent_from_smoke_and_gateway_logs"] = True
    return result


def main() -> None:
    try:
        result = asyncio.run(_run())
    except Exception as error:
        detail = str(error)
        for value in (
            os.environ.get("VERBAOPS_AGENT_FAST_API_KEY", ""),
            *(
                _read_local_stack()[0].values()
                if STACK_ENV.is_file() and STACK_STATE.is_file()
                else ()
            ),
        ):
            if value:
                detail = detail.replace(value, "[redacted]")
        raise SystemExit(
            f"sanitized genuine agent-fast smoke failed ({type(error).__name__}): "
            f"{' '.join(detail.split())[-400:]}"
        ) from None
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
