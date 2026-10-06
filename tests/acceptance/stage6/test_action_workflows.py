"""Provider-free public HTTP acceptance for the five normal Stage 6 actions."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

import httpx

from .conftest import (
    commerce_headers,
    durable_action,
    headers,
    overlay_id,
    propose,
    scenario_id,
    tool_trace,
)


def _confirm(client: httpx.Client, token: str, action_id: UUID, fingerprint: str) -> dict[str, Any]:
    response = client.post(
        f"/v1/action-requests/{action_id}/confirmation",
        headers=headers(token),
        json={"proposal_fingerprint": fingerprint},
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


def test_reschedule_requires_customer_only_and_verifies_exact_slot(
    client: httpx.Client,
    commerce_client: httpx.Client,
    customer_token: str,
    commerce_token: str,
    manifest: dict[str, object],
    database_url: str,
) -> None:
    order_id = overlay_id(manifest, "reschedulable_order")
    target_slot = overlay_id(manifest, "slot_y")
    conversation_id, summary, view = propose(
        client,
        customer_token,
        "propose_reschedule_delivery",
        {
            "action_type": "reschedule_delivery",
            "order_id": order_id,
            "delivery_slot_id": target_slot,
        },
    )
    assert summary["state"] == view["state"] == "awaiting_confirmation"
    assert view["approval_required"] is False
    assert view["permitted_operations"] == ["confirm", "reject"]

    result = _confirm(
        client,
        customer_token,
        UUID(summary["action_request_id"]),
        summary["proposal_fingerprint"],
    )
    assert result["state"] == "succeeded", durable_action(
        database_url, UUID(summary["action_request_id"])
    )
    assert result["result_status"] == "verified"
    shipment = commerce_client.get(
        f"/v1/orders/{order_id}/shipment",
        headers=commerce_headers(commerce_token, scenario_id(manifest, "customer_primary")),
    )
    assert shipment.status_code == 200
    assert shipment.json()["delivery_slot_id"] == target_slot

    trace = durable_action(database_url, UUID(summary["action_request_id"]))
    assert str(trace["action"]["idempotency_key"])
    assert [event["event_type"] for event in trace["events"]] == [
        "created",
        "policy_allowed",
        "customer_confirmed",
        "execution_started",
        "commerce_response",
        "verification_succeeded",
    ]
    assert all(
        row["tool_name"].startswith("propose_") for row in tool_trace(database_url, conversation_id)
    )


def test_ordinary_cancellation_is_customer_confirmed_and_verified(
    client: httpx.Client,
    commerce_client: httpx.Client,
    customer_token: str,
    commerce_token: str,
    manifest: dict[str, object],
    database_url: str,
) -> None:
    order_id = overlay_id(manifest, "ordinary_cancel_order")
    _, summary, view = propose(
        client,
        customer_token,
        "propose_cancel_order",
        {"action_type": "cancel_order", "order_id": order_id},
    )
    assert view["state"] == "awaiting_confirmation"
    assert view["approval_required"] is False
    result = _confirm(
        client, customer_token, UUID(summary["action_request_id"]), summary["proposal_fingerprint"]
    )
    assert result["state"] == "succeeded", {
        key: result.get(key)
        for key in ("state", "reason_code", "result_status", "error_code", "status_code")
    }
    order = commerce_client.get(
        f"/v1/orders/{order_id}",
        headers=commerce_headers(commerce_token, scenario_id(manifest, "customer_primary")),
    )
    assert order.status_code == 200
    assert order.json()["status"] == "cancelled"


def test_unusual_cancellation_requires_different_supervisor_then_customer(
    client: httpx.Client,
    commerce_client: httpx.Client,
    customer_token: str,
    supervisor_token: str,
    commerce_token: str,
    manifest: dict[str, object],
    database_url: str,
) -> None:
    order_id = overlay_id(manifest, "unusual_cancel_order")
    _, summary, view = propose(
        client,
        customer_token,
        "propose_cancel_order",
        {"action_type": "cancel_order", "order_id": order_id},
    )
    action_id = UUID(summary["action_request_id"])
    assert view["state"] == "awaiting_approval"
    assert view["approval_required"] is True
    assert view["permitted_operations"] == ["reject"]

    approved = client.post(
        f"/v1/action-requests/{action_id}/approval",
        headers=headers(supervisor_token),
        json={"proposal_fingerprint": summary["proposal_fingerprint"]},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["state"] == "awaiting_confirmation"

    result = _confirm(client, customer_token, action_id, summary["proposal_fingerprint"])
    assert result["state"] == "succeeded", durable_action(database_url, action_id)
    order = commerce_client.get(
        f"/v1/orders/{order_id}",
        headers=commerce_headers(commerce_token, scenario_id(manifest, "customer_primary")),
    )
    assert order.status_code == 200
    assert order.json()["status"] == "cancelled"


def test_return_verifies_material_items_and_return_readback(
    client: httpx.Client,
    commerce_client: httpx.Client,
    customer_token: str,
    commerce_token: str,
    manifest: dict[str, object],
    database_url: str,
) -> None:
    order_id = overlay_id(manifest, "recent_delivered_order")
    item_id = overlay_id(manifest, "recent_order_item")
    _, summary, view = propose(
        client,
        customer_token,
        "propose_return",
        {
            "action_type": "initiate_return",
            "order_id": order_id,
            "items": [{"order_item_id": item_id, "quantity": 1}],
            "reason": "Acceptance return",
        },
    )
    assert view["state"] == "awaiting_confirmation"
    result = _confirm(
        client, customer_token, UUID(summary["action_request_id"]), summary["proposal_fingerprint"]
    )
    assert result["state"] == "succeeded", {
        key: result.get(key)
        for key in ("state", "reason_code", "result_status", "error_code", "status_code")
    }
    durable = durable_action(database_url, UUID(summary["action_request_id"]))
    return_id = durable["action"]["commerce_resource_id"]
    assert return_id is not None
    read_back = commerce_client.get(
        f"/v1/returns/{return_id}",
        headers=commerce_headers(commerce_token, scenario_id(manifest, "customer_primary")),
    )
    assert read_back.status_code == 200
    assert read_back.json()["order_id"] == order_id
    assert [
        {"order_item_id": item["order_item_id"], "quantity": item["quantity"]}
        for item in read_back.json()["items"]
    ] == [{"order_item_id": item_id, "quantity": 1}]
    assert "refund" not in result["safe_summary"].lower()


def test_support_ticket_verifies_category_and_material_fields(
    client: httpx.Client,
    commerce_client: httpx.Client,
    customer_token: str,
    commerce_token: str,
    manifest: dict[str, object],
    database_url: str,
) -> None:
    _, summary, view = propose(
        client,
        customer_token,
        "propose_support_ticket",
        {
            "action_type": "create_support_ticket",
            "order_id": None,
            "category": "delivery",
            "subject": "Delivery question",
            "description": "Please explain the delivery window.",
        },
    )
    assert view["state"] == "awaiting_confirmation"
    result = _confirm(
        client, customer_token, UUID(summary["action_request_id"]), summary["proposal_fingerprint"]
    )
    assert result["state"] == "succeeded", {
        key: result.get(key)
        for key in ("state", "reason_code", "result_status", "error_code", "status_code")
    }
    durable = durable_action(database_url, UUID(summary["action_request_id"]))
    ticket_id = durable["action"]["commerce_resource_id"]
    assert ticket_id is not None
    ticket = commerce_client.get(
        f"/v1/support-tickets/{ticket_id}",
        headers=commerce_headers(commerce_token, scenario_id(manifest, "customer_primary")),
    )
    assert ticket.status_code == 200
    assert ticket.json()["category"] == "delivery"
    assert ticket.json()["subject"] == "Delivery question"
    assert ticket.json()["description"] == "Please explain the delivery window."
