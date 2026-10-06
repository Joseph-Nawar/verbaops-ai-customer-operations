"""Stage 6 public-boundary, scope, freshness, and audit safety assertions."""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import httpx

from .conftest import durable_action, headers, overlay_id, propose, scenario_id, tool_trace


def test_model_proposals_cannot_supply_identity_state_or_write_authority(
    client: httpx.Client,
    customer_token: str,
    manifest: dict[str, object],
    database_url: str,
) -> None:
    conversation_id = UUID(
        client.post("/v1/conversations", headers=headers(customer_token), json={}).json()[
            "conversation_id"
        ]
    )
    response = client.post(
        f"/v1/conversations/{conversation_id}/messages",
        headers=headers(customer_token),
        json={
            "content": "stage6-propose:"
            + json.dumps(
                {
                    "tool": "propose_cancel_order",
                    "arguments": {
                        "action_type": "cancel_order",
                        "order_id": scenario_id(manifest, "order_cancellable"),
                        "tenant_id": str(uuid4()),
                        "customer_id": str(uuid4()),
                        "principal_id": str(uuid4()),
                        "role": "support_supervisor",
                        "state": "succeeded",
                        "idempotency_key": str(uuid4()),
                    },
                },
                separators=(",", ":"),
            ),
        },
    )
    assert response.status_code in {200, 502}
    assert response.status_code == 200
    assert response.json()["action_requests"] == []
    assert all(
        row["tool_name"] not in {"execute_action", "approve_action", "confirm_action"}
        for row in tool_trace(database_url, conversation_id)
    )


def test_action_get_is_observational_and_active_reload_uses_durable_rows(
    client: httpx.Client,
    customer_token: str,
    manifest: dict[str, object],
    database_url: str,
) -> None:
    conversation_id, summary, before = propose(
        client,
        customer_token,
        "propose_reschedule_delivery",
        {
            "action_type": "reschedule_delivery",
            "order_id": overlay_id(manifest, "reschedulable_order"),
            "delivery_slot_id": overlay_id(manifest, "slot_x"),
        },
    )
    action_id = UUID(summary["action_request_id"])
    durable_before = durable_action(database_url, action_id)
    first = client.get(f"/v1/action-requests/{action_id}", headers=headers(customer_token))
    second = client.get(f"/v1/action-requests/{action_id}", headers=headers(customer_token))
    reloaded = client.get(
        f"/v1/conversations/{conversation_id}",
        headers=headers(customer_token),
        params={"limit": 100},
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["state"] == second.json()["state"] == before["state"]
    assert durable_action(database_url, action_id) == durable_before
    assert reloaded.status_code == 200
    assert [item["action_request_id"] for item in reloaded.json()["active_action_requests"]] == [
        str(action_id)
    ]
    assert all(
        event["event_type"] not in {"expired", "state_transition"}
        for event in durable_before["events"]
    )


def test_cross_customer_action_and_conversation_are_non_enumerating(
    client: httpx.Client,
    customer_token: str,
    other_customer_token: str,
    manifest: dict[str, object],
) -> None:
    _, summary, _ = propose(
        client,
        customer_token,
        "propose_reschedule_delivery",
        {
            "action_type": "reschedule_delivery",
            "order_id": overlay_id(manifest, "reschedulable_order"),
            "delivery_slot_id": overlay_id(manifest, "slot_x"),
        },
    )
    action_id = summary["action_request_id"]
    foreign = client.get(f"/v1/action-requests/{action_id}", headers=headers(other_customer_token))
    random = client.get(f"/v1/action-requests/{uuid4()}", headers=headers(other_customer_token))
    assert foreign.status_code == random.status_code == 404
    assert foreign.json()["error"]["code"] == random.json()["error"]["code"]
    assert foreign.json()["error"]["message"] == random.json()["error"]["message"]


def test_self_approval_is_rejected_without_a_decision_event(
    client: httpx.Client,
    customer_token: str,
    manifest: dict[str, object],
    database_url: str,
) -> None:
    _, summary, _ = propose(
        client,
        customer_token,
        "propose_refund",
        {
            "action_type": "request_refund",
            "order_id": scenario_id(manifest, "order_refund_501_00"),
            "amount": "501.00",
            "reason": "Self approval test",
        },
    )
    action_id = UUID(summary["action_request_id"])
    response = client.post(
        f"/v1/action-requests/{action_id}/approval",
        headers=headers("stage6-self-approver-token"),
        json={"proposal_fingerprint": summary["proposal_fingerprint"]},
    )
    assert response.status_code == 403
    events = durable_action(database_url, action_id)["events"]
    assert all(event["event_type"] != "supervisor_approved" for event in events)


def test_stale_confirmation_expires_without_a_second_commerce_write(
    client: httpx.Client,
    commerce_client: httpx.Client,
    customer_token: str,
    supervisor_token: str,
    commerce_token: str,
    manifest: dict[str, object],
    database_url: str,
) -> None:
    order_id = overlay_id(manifest, "stale_cancel_order")
    _, summary, _ = propose(
        client,
        customer_token,
        "propose_cancel_order",
        {"action_type": "cancel_order", "order_id": order_id},
    )
    approved = client.post(
        f"/v1/action-requests/{summary['action_request_id']}/approval",
        headers=headers(supervisor_token),
        json={"proposal_fingerprint": summary["proposal_fingerprint"]},
    )
    assert approved.status_code == 200
    changed = commerce_client.post(
        f"/v1/orders/{order_id}/cancel",
        headers={
            **{
                "Authorization": f"Bearer {commerce_token}",
                "X-VerbaOps-Customer-ID": scenario_id(manifest, "customer_primary"),
                "Idempotency-Key": f"acceptance-stale-{uuid4()}",
            }
        },
    )
    assert changed.status_code == 200, changed.text
    response = client.post(
        f"/v1/action-requests/{summary['action_request_id']}/confirmation",
        headers=headers(customer_token),
        json={"proposal_fingerprint": summary["proposal_fingerprint"]},
    )
    assert response.status_code == 409
    assert (
        durable_action(database_url, UUID(summary["action_request_id"]))["action"]["state"]
        == "expired"
    )
