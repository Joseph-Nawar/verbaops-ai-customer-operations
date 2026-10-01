"""Run the local, checkpoint-safe M5D DEV calibration with isolated services."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from argparse import Namespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _local_settings() -> tuple[dict[str, str], dict[str, object]]:
    values = {
        key: value
        for line in (ROOT / "artifacts/m5d/stack/local.env")
        .read_text(encoding="utf-8")
        .splitlines()
        if line and "=" in line
        for key, value in [line.split("=", 1)]
    }
    state = json.loads((ROOT / "artifacts/m5d/stack/stack.json").read_text(encoding="utf-8"))
    database_url = (
        f"postgresql+asyncpg://{values['VERBAOPS_DB_USER']}:{values['VERBAOPS_DB_PASSWORD']}"
        f"@127.0.0.1:{state['database_port']}/{values['VERBAOPS_DB_NAME']}"
    )
    gateway_url = f"http://127.0.0.1:{state['gateway_port']}/v1"
    os.environ["VERBAOPS_DATABASE__URL"] = database_url
    os.environ["VERBAOPS_LLM__BASE_URL"] = gateway_url
    os.environ["VERBAOPS_LLM__API_KEY"] = values["LITELLM_MASTER_KEY"]
    return values, state


async def main() -> None:
    from scripts.run_m5d_gate_eval import _run

    _local_settings()
    state = json.loads((ROOT / "artifacts/m5d/stack/stack.json").read_text(encoding="utf-8"))
    args = Namespace(
        split="dev",
        run_dir=ROOT / "artifacts/m5d/gate-calibration",
        database_url=os.environ["VERBAOPS_DATABASE__URL"],
        embedding_gateway_url=os.environ["VERBAOPS_LLM__BASE_URL"],
        embedding_gateway_key=os.environ["VERBAOPS_LLM__API_KEY"],
        reranker_url=f"http://127.0.0.1:{state['reranker_tei_port']}",
        timeout_seconds=60.0,
    )
    await _run(args)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(f"M5D DEV gate calibration failed ({type(error).__name__})") from None
