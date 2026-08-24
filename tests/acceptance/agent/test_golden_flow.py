"""Permanent public-HTTP and read-only trace acceptance for M3E."""

import asyncio
import os
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.acceptance.agent.conftest import scenario_id


def _database_url() -> str:
    value = os.environ.get("AGENT_ACCEPTANCE_DATABASE_URL")
    if not value:
        pytest.fail("AGENT_ACCEPTANCE_DATABASE_URL is required for trace assertions")
    return value


async def _trace(conversation_id: str) -> dict[str, Any]:
    engine = create_async_engine(_database_url(), pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            conversation_count = await connection.scalar(
                text("SELECT count(*) FROM conversations WHERE id = :id"),
                {"id": conversation_id},
            )
            visible_messages = await connection.scalar(
                text(
                    "SELECT count(*) FROM messages "
                    "WHERE conversation_id = :id AND role IN ('user', 'assistant')"
                ),
                {"id": conversation_id},
            )
            run_rows = (
                (
                    await connection.execute(
                        text(
                            "SELECT status, graph_version, prompt_version, tool_schema_version "
                            "FROM agent_runs WHERE conversation_id = :id ORDER BY started_at"
                        ),
                        {"id": conversation_id},
                    )
                )
                .mappings()
                .all()
            )
            model_calls = await connection.scalar(
                text(
                    "SELECT count(*) FROM model_calls mc "
                    "JOIN agent_runs ar ON ar.id = mc.agent_run_id "
                    "WHERE ar.conversation_id = :id"
                ),
                {"id": conversation_id},
            )
            tool_rows = (
                (
                    await connection.execute(
                        text(
                            "SELECT ti.tool_name, ti.risk_level, ti.status, ti.result_json "
                            "FROM tool_invocations ti "
                            "JOIN agent_runs ar ON ar.id = ti.agent_run_id "
                            "WHERE ar.conversation_id = :id ORDER BY ti.sequence"
                        ),
                        {"id": conversation_id},
                    )
                )
                .mappings()
                .all()
            )
            write_tools = await connection.scalar(
                text(
                    "SELECT count(*) FROM tool_invocations ti "
                    "JOIN agent_runs ar ON ar.id = ti.agent_run_id "
                    "WHERE ar.conversation_id = :id "
                    "AND ti.tool_name NOT IN "
                    "('get_order_status', 'get_shipment_status', 'get_refund_status', "
                    "'search_products', 'list_delivery_slots')"
                ),
                {"id": conversation_id},
            )
        return {
            "conversation_count": int(conversation_count or 0),
            "visible_messages": int(visible_messages or 0),
            "runs": [dict(row) for row in run_rows],
            "model_calls": int(model_calls or 0),
            "tools": [dict(row) for row in tool_rows],
            "write_tools": int(write_tools or 0),
        }
    finally:
        await engine.dispose()


@pytest.mark.agent_acceptance
def test_golden_read_only_agent_flow_is_grounded_and_persisted(
    client: httpx.Client,
    authenticated_headers: dict[str, str],
    manifest: dict[str, object],
) -> None:
    missing = client.post("/v1/conversations", json={})
    invalid = client.post(
        "/v1/conversations", headers={"Authorization": "Bearer invalid-token"}, json={}
    )
    assert missing.status_code == invalid.status_code == 401
    assert (
        missing.json()["error"]["code"]
        == invalid.json()["error"]["code"]
        == "authentication_failed"
    )

    extra_identity = client.post(
        "/v1/conversations",
        headers=authenticated_headers,
        json={"customer_id": scenario_id(manifest, "customer_primary")},
    )
    assert extra_identity.status_code == 422

    created = client.post("/v1/conversations", headers=authenticated_headers, json={})
    assert created.status_code == 201
    conversation_id = created.json()["conversation_id"]
    assert "tenant_id" not in created.text
    assert "principal_id" not in created.text
    assert "customer_id" not in created.text

    clarification = client.post(
        f"/v1/conversations/{conversation_id}/messages",
        headers=authenticated_headers,
        json={"content": "Where is my order?"},
    )
    assert clarification.status_code == 200
    assert "order ID" in clarification.json()["assistant_message"]["content"]

    order_id = scenario_id(manifest, "order_already_shipped")
    grounded = client.post(
        f"/v1/conversations/{conversation_id}/messages",
        headers=authenticated_headers,
        json={"content": order_id},
    )
    assert grounded.status_code == 200
    final_answer = grounded.json()["assistant_message"]["content"]

    visible = client.get(
        f"/v1/conversations/{conversation_id}",
        headers=authenticated_headers,
        params={"limit": 100},
    )
    assert visible.status_code == 200
    visible_payload = visible.json()
    assert [message["role"] for message in visible_payload["messages"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert len(visible_payload["messages"]) == 4
    assert "agent_runs" not in visible.text
    assert "tool_invocations" not in visible.text

    unknown = client.get(
        "/v1/conversations/00000000-0000-0000-0000-000000000099",
        headers=authenticated_headers,
    )
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "conversation_not_found"

    trace = asyncio.run(_trace(conversation_id))
    assert trace["conversation_count"] == 1
    assert trace["visible_messages"] == 4
    assert trace["model_calls"] == 3
    assert trace["write_tools"] == 0
    assert len(trace["runs"]) == 2
    assert all(row["status"] == "completed" for row in trace["runs"])
    assert all(row["graph_version"] == "text-agent-v1" for row in trace["runs"])
    assert all(row["prompt_version"] == "text-agent-system-v1" for row in trace["runs"])
    assert all(row["tool_schema_version"] == "commerce-read-tools-v1" for row in trace["runs"])
    assert len(trace["tools"]) == 1
    tool = trace["tools"][0]
    assert tool["tool_name"] == "get_shipment_status"
    assert tool["risk_level"] == "read_only"
    assert tool["status"] == "succeeded"
    result = tool["result_json"]
    assert isinstance(result, dict)
    assert str(result["status"]) in final_answer
    assert str(result["carrier"]) in final_answer
    if result["tracking_number"] is not None:
        assert str(result["tracking_number"]) in final_answer
