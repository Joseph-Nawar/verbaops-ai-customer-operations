"""Ingest and verify NovaCommerce into the isolated M5D DEV database."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ENV_FILE = ROOT / "artifacts/m5d/stack/local.env"
STATE_FILE = ROOT / "artifacts/m5d/stack/stack.json"
TENANT_ID = UUID("10000000-0000-0000-0000-000000000002")


def _load_environment() -> tuple[dict[str, str], dict[str, object]]:
    env: dict[str, str] = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line and "=" in line:
            key, value = line.split("=", 1)
            env[key] = value
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return env, state


async def _run() -> None:
    from scripts.ingest_rag_benchmark import ingest
    from scripts.verify_m5d_eval_database import _verify

    values, state = _load_environment()
    database_url = (
        f"postgresql+asyncpg://{values['VERBAOPS_DB_USER']}:{values['VERBAOPS_DB_PASSWORD']}"
        f"@127.0.0.1:{state['database_port']}/{values['VERBAOPS_DB_NAME']}"
    )
    gateway_url = f"http://127.0.0.1:{state['gateway_port']}/v1"
    os.environ["VERBAOPS_DATABASE__URL"] = database_url
    os.environ["VERBAOPS_LLM__BASE_URL"] = gateway_url
    os.environ["VERBAOPS_LLM__API_KEY"] = values["LITELLM_MASTER_KEY"]
    await ingest(ROOT, database_url, TENANT_ID, gateway_url)
    verified = await _verify(database_url)
    print(json.dumps({"ingest": "complete", "database": verified}, sort_keys=True))


def main() -> None:
    try:
        asyncio.run(_run())
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(f"M5D corpus preparation failed ({type(error).__name__})") from None


if __name__ == "__main__":
    main()
