"""Make one safe M0 provider smoke and print only sanitized metadata."""

from __future__ import annotations

import argparse
import asyncio
import json
import os

import httpx
from pydantic import SecretStr

from verbaops.config.settings import LLMSettings
from verbaops.llm.litellm import LiteLLMClient
from verbaops.llm.models import CapabilityAlias, ChatMessage, GenerateRequest


async def _smoke(gateway_url: str, gateway_key: str) -> dict[str, object]:
    async with httpx.AsyncClient(timeout=40.0) as client:
        gateway_root = gateway_url.rstrip("/")
        if gateway_root.endswith("/v1"):
            gateway_root = gateway_root[:-3]
        health = await client.get(f"{gateway_root}/health/liveliness")
        health.raise_for_status()
        llm = LiteLLMClient(
            LLMSettings(base_url=gateway_url, api_key=SecretStr(gateway_key), timeout_seconds=35),
            client,
        )
        response = await llm.generate(
            GenerateRequest(
                capability=CapabilityAlias.AGENT_FAST,
                messages=(
                    ChatMessage(
                        role="user",
                        content="For a harmless connection check, reply exactly: M5D smoke passed",
                    ),
                ),
                max_tokens=256,
                tools=(),
                tool_choice="none",
            )
        )
    if not response.content or not response.content.strip():
        raise RuntimeError("agent-fast smoke returned no content")
    metadata = response.metadata
    if metadata.capability_alias is not CapabilityAlias.AGENT_FAST:
        raise RuntimeError("agent-fast smoke metadata did not identify the expected alias")
    if not metadata.model:
        raise RuntimeError("agent-fast smoke did not return model metadata")
    return {
        "gateway_healthy": True,
        "agent_fast_resolved": True,
        "request_succeeded": True,
        "capability_alias": metadata.capability_alias.value,
        "model": metadata.model,
        "provider": metadata.provider,
        "configured_provider_family": "groq",
        "provider_metadata_source": (
            "gateway" if metadata.provider is not None else "configured_model_route"
        ),
        "gateway_model_id": metadata.gateway_model_id,
        "latency_ms": metadata.latency_ms,
        "cost_usd": metadata.cost_usd,
        "response_content_printed": False,
        "credential_output": "none",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway-url", required=True)
    args = parser.parse_args()
    gateway_key = os.environ.get("LITELLM_MASTER_KEY")
    if not gateway_key:
        raise SystemExit("local LiteLLM gateway key is missing")
    try:
        result = asyncio.run(_smoke(args.gateway_url, gateway_key))
    except Exception as error:
        raise SystemExit(f"sanitized agent-fast smoke failed ({type(error).__name__})") from None
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
