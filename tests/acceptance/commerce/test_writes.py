"""Authenticated write contracts exercised only through HTTP."""

import httpx

from .conftest import overlay_id, scenario_id


def test_create_get_reschedule_cancel_and_replays(
    client: httpx.Client,
    primary_headers: dict[str, str],
    authenticated_headers: dict[str, str],
    manifest: dict[str, object],
    idempotency_key: str,
) -> None:
    product = overlay_id(manifest, "overlay_product")
    created = client.post(
        "/v1/orders",
        headers={**primary_headers, "Idempotency-Key": idempotency_key},
        json={"items": [{"product_id": product, "quantity": 1}]},
    )
    assert created.status_code == 201
    order_id = created.json()["order"]["id"]
    assert created.headers.get("x-idempotent-replay") is None
    replay = client.post(
        "/v1/orders",
        headers={**primary_headers, "Idempotency-Key": idempotency_key},
        json={"items": [{"product_id": product, "quantity": 1}]},
    )
    assert replay.status_code == 201
    assert replay.headers["x-idempotent-replay"] == "true"
    assert replay.json() == created.json()
    assert client.get(f"/v1/orders/{order_id}", headers=primary_headers).status_code == 200

    reschedule_key = idempotency_key + "-reschedule"
    shipment_id = created.json()["shipment"]["id"]
    slots = client.get("/v1/delivery-slots", headers=authenticated_headers).json()
    target = next(item["id"] for item in slots if item["available"])
    rescheduled = client.post(
        f"/v1/orders/{order_id}/reschedule",
        headers={**primary_headers, "Idempotency-Key": reschedule_key},
        json={"delivery_slot_id": target},
    )
    assert rescheduled.status_code == 200
    assert rescheduled.json()["id"] == shipment_id
    assert (
        client.post(
            f"/v1/orders/{order_id}/reschedule",
            headers={**primary_headers, "Idempotency-Key": reschedule_key},
            json={"delivery_slot_id": target},
        ).headers["x-idempotent-replay"]
        == "true"
    )

    cancel_key = idempotency_key + "-cancel"
    cancelled = client.post(
        f"/v1/orders/{order_id}/cancel",
        headers={**primary_headers, "Idempotency-Key": cancel_key},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["order"]["status"] == "cancelled"
    cancel_replay = client.post(
        f"/v1/orders/{order_id}/cancel",
        headers={**primary_headers, "Idempotency-Key": cancel_key},
    )
    assert cancel_replay.status_code == 200
    assert cancel_replay.headers["x-idempotent-replay"] == "true"


def test_return_refunds_ticket_and_business_rejections(
    client: httpx.Client,
    primary_headers: dict[str, str],
    manifest: dict[str, object],
    idempotency_key: str,
) -> None:
    order = overlay_id(manifest, "recent_delivered_order")
    order_payload = client.get(f"/v1/orders/{order}", headers=primary_headers).json()
    item_id = order_payload["items"][0]["order_item_id"]
    returned = client.post(
        "/v1/returns",
        headers={**primary_headers, "Idempotency-Key": idempotency_key},
        json={
            "order_id": order,
            "reason": "Acceptance test",
            "items": [{"order_item_id": item_id, "quantity": 1}],
        },
    )
    assert returned.status_code == 201

    for name, amount, status, manual in (
        ("order_refund_499_99", "499.99", "approved", False),
        ("order_refund_500_00", "500.00", "approved", False),
        ("order_refund_501_00", "501.00", "pending_manual_approval", True),
    ):
        response = client.post(
            f"/v1/orders/{scenario_id(manifest, name)}/refunds",
            headers={**primary_headers, "Idempotency-Key": f"{idempotency_key}-{name}"},
            json={"amount": amount, "reason": "Acceptance test"},
        )
        assert response.status_code == 201
        assert response.json()["status"] == status
        assert response.json()["requires_manual_approval"] is manual

    ticket = client.post(
        "/v1/support-tickets",
        headers={**primary_headers, "Idempotency-Key": idempotency_key + "-ticket"},
        json={"subject": "Acceptance", "description": "Black-box acceptance ticket"},
    )
    assert ticket.status_code == 201

    rejected = client.post(
        f"/v1/orders/{scenario_id(manifest, 'order_already_shipped')}/cancel",
        headers={**primary_headers, "Idempotency-Key": idempotency_key + "-rejected"},
    )
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "order_not_cancellable"


def test_same_key_conflict_and_cross_customer_target_are_safe(
    client: httpx.Client,
    primary_headers: dict[str, str],
    manifest: dict[str, object],
    idempotency_key: str,
) -> None:
    product = overlay_id(manifest, "overlay_product")
    first = client.post(
        "/v1/orders",
        headers={**primary_headers, "Idempotency-Key": idempotency_key},
        json={"items": [{"product_id": product, "quantity": 1}]},
    )
    assert first.status_code == 201
    changed_body = client.post(
        "/v1/orders",
        headers={**primary_headers, "Idempotency-Key": idempotency_key},
        json={"items": [{"product_id": product, "quantity": 2}]},
    )
    assert changed_body.status_code == 409
    assert changed_body.json()["error"]["code"] == "idempotency_key_reused"

    other = scenario_id(manifest, "order_other_customer")
    cross_customer = client.post(
        f"/v1/orders/{other}/cancel",
        headers={**primary_headers, "Idempotency-Key": idempotency_key + "-cross"},
    )
    assert cross_customer.status_code == 404
