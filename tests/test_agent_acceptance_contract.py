"""Structural contract tests for the disposable M3E acceptance stack."""

from pathlib import Path

from scripts.llm_test_provider import _completion

from verbaops.agent.versions import GRAPH_VERSION, PROMPT_VERSION, TOOL_SCHEMA_VERSION
from verbaops.tools.registry import build_commerce_read_registry

COMPOSE = Path("docker-compose.agent-acceptance.yml")
RUNNER = Path("scripts/run_agent_acceptance.py")


def test_agent_acceptance_stack_contains_only_required_backend_services() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    for service in (
        "verbaops-postgres:",
        "verbaops-migrate:",
        "verbaops-api:",
        "commerce-postgres:",
        "commerce-migrate:",
        "commerce-seed:",
        "commerce-api:",
        "provider-stub:",
        "llm-gateway:",
    ):
        assert service in text
    assert "ghcr.io/berriai/litellm:v1.98.0@sha256:" in text
    assert "latest" not in text.lower()
    assert "redis:" not in text


def test_agent_acceptance_provenance_is_m5b_and_commerce_tools_are_unchanged() -> None:
    assert GRAPH_VERSION == "text-agent-v2"
    assert PROMPT_VERSION == "text-agent-system-v2"
    assert TOOL_SCHEMA_VERSION == "commerce-read-tools-v1"
    assert [tool.name for tool in build_commerce_read_registry()] == [
        "get_order_status",
        "get_shipment_status",
        "get_refund_status",
        "search_products",
        "list_delivery_slots",
    ]


def test_agent_acceptance_runner_generates_and_destroys_ephemeral_secrets() -> None:
    text = RUNNER.read_text(encoding="utf-8")
    for generator in ("secrets.token_urlsafe", "tempfile.NamedTemporaryFile", "--volumes"):
        assert generator in text
    assert ".env" in text
    assert ".secrets" not in text
    assert "AGENT_ACCEPTANCE_TOKEN" in text
    assert "AGENT_ACCEPTANCE_DATABASE_URL" in text


def test_deterministic_provider_implements_the_three_request_journey() -> None:
    first = _completion(
        {
            "messages": [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "Where is my order?"},
            ],
            "tools": [],
        }
    )
    assert first["choices"][0]["message"]["content"].startswith("Please provide")

    order_id = "45fd2b63-ce1b-52ae-baf6-96d8cd9f4aa2"
    second = _completion(
        {
            "messages": [
                {"role": "user", "content": "Where is my order?"},
                {"role": "assistant", "content": "Please provide your order ID."},
                {"role": "user", "content": order_id},
            ],
            "tools": [{"type": "function", "function": {"name": "get_shipment_status"}}],
        }
    )
    call = second["choices"][0]["message"]["tool_calls"][0]
    assert call["function"]["name"] == "get_shipment_status"
    assert call["function"]["arguments"] == '{"order_id": "' + order_id + '"}'

    final = _completion(
        {
            "messages": [
                {"role": "user", "content": order_id},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [call],
                },
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": '{"carrier":"Acme","status":"in_transit","tracking_number":"T-1"}',
                },
            ],
            "tools": [],
        }
    )
    assert "in_transit" in final["choices"][0]["message"]["content"]
    assert "T-1" in final["choices"][0]["message"]["content"]
