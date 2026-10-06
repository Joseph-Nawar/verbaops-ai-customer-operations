"""Provider-free refund threshold and no-payment-settlement acceptance."""

from __future__ import annotations

from typing import cast
from uuid import UUID

import httpx

from .conftest import commerce_headers, durable_action, headers, propose, scenario_id


def _refund(
    client: httpx.Client,
    customer_token: str,
    manifest: dict[str, object],
    order_name: str,
    amount: str,
    reason: str,
) -> tuple[dict[str, object], dict[str, object]]:
    _, summary, view = propose(
        client,
        customer_token,
        "propose_refund",
        {
            "action_type": "request_refund",
            "order_id": scenario_id(manifest, order_name),
            "amount": amount,
            "reason": reason,
        },
    )
    return summary, view


def test_499_99_and_500_00_are_customer_only_verified_requests(
    client: httpx.Client,
    commerce_client: httpx.Client,
    customer_token: str,
    commerce_token: str,
    manifest: dict[str, object],
    database_url: str,
) -> None:
    for order_name, amount in (
        ("order_refund_499_99", "499.99"),
        ("order_refund_500_00", "500.00"),
    ):
        summary, view = _refund(
            client, customer_token, manifest, order_name, amount, "Threshold test"
        )
        assert view["state"] == "awaiting_confirmation"
        assert view["approval_required"] is False
        assert view["currency_code"] == "USD"
        result = client.post(
            f"/v1/action-requests/{summary['action_request_id']}/confirmation",
            headers=headers(customer_token),
            json={"proposal_fingerprint": summary["proposal_fingerprint"]},
        )
        assert result.status_code == 200, result.text
        assert result.json()["state"] == "succeeded"
        assert "payment" in result.json()["safe_summary"].lower()
        refunds = commerce_client.get(
            f"/v1/orders/{scenario_id(manifest, order_name)}/refunds",
            headers=commerce_headers(commerce_token, scenario_id(manifest, "customer_primary")),
        )
        assert refunds.status_code == 200
        matching = [row for row in refunds.json() if row["amount"] == amount]
        assert matching and matching[-1]["status"] == "approved"
        assert matching[-1]["requires_manual_approval"] is False
        durable = durable_action(database_url, UUID(cast(str, summary["action_request_id"])))
        assert durable["action"]["verification_status"] == "verified"


def test_500_01_requires_durable_supervisor_approval_before_customer_write(
    client: httpx.Client,
    commerce_client: httpx.Client,
    customer_token: str,
    supervisor_token: str,
    commerce_token: str,
    manifest: dict[str, object],
    database_url: str,
) -> None:
    summary, view = _refund(
        client, customer_token, manifest, "order_refund_501_00", "500.01", "High-value boundary"
    )
    action_id = UUID(cast(str, summary["action_request_id"]))
    assert view["state"] == "awaiting_approval"
    assert view["approval_required"] is True
    assert view["permitted_operations"] == ["reject"]
    before = client.post(
        f"/v1/action-requests/{action_id}/confirmation",
        headers=headers(customer_token),
        json={"proposal_fingerprint": summary["proposal_fingerprint"]},
    )
    assert before.status_code == 409

    approved = client.post(
        f"/v1/action-requests/{action_id}/approval",
        headers=headers(supervisor_token),
        json={"proposal_fingerprint": summary["proposal_fingerprint"]},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["state"] == "awaiting_confirmation"
    confirmed = client.post(
        f"/v1/action-requests/{action_id}/confirmation",
        headers=headers(customer_token),
        json={"proposal_fingerprint": summary["proposal_fingerprint"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["state"] == "succeeded"
    assert "payment" in confirmed.json()["safe_summary"].lower()

    refunds = commerce_client.get(
        f"/v1/orders/{scenario_id(manifest, 'order_refund_501_00')}/refunds",
        headers=commerce_headers(commerce_token, scenario_id(manifest, "customer_primary")),
    )
    assert refunds.status_code == 200
    matching = [row for row in refunds.json() if row["amount"] == "500.01"]
    assert matching and matching[-1]["status"] == "approved"
    assert matching[-1]["requires_manual_approval"] is True
    assert durable_action(database_url, action_id)["action"]["verification_status"] == "verified"
