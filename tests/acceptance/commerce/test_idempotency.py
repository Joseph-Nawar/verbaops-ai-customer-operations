"""Persistent idempotency behavior visible only through HTTP."""

import httpx

from .conftest import overlay_id, scenario_id


def test_deterministic_business_rejection_is_replayed(
    client: httpx.Client,
    primary_headers: dict[str, str],
    manifest: dict[str, object],
    idempotency_key: str,
) -> None:
    path = f"/v1/orders/{scenario_id(manifest, 'order_already_shipped')}/cancel"
    first = client.post(path, headers={**primary_headers, "Idempotency-Key": idempotency_key})
    second = client.post(path, headers={**primary_headers, "Idempotency-Key": idempotency_key})
    assert first.status_code == second.status_code == 409
    assert first.json() == second.json()
    assert second.headers["x-idempotent-replay"] == "true"
    assert first.json()["error"]["code"] == "order_not_cancellable"


def test_same_key_different_target_and_operation_conflict(
    client: httpx.Client,
    primary_headers: dict[str, str],
    manifest: dict[str, object],
    idempotency_key: str,
) -> None:
    created = client.post(
        "/v1/orders",
        headers={**primary_headers, "Idempotency-Key": idempotency_key + "-create"},
        json={"items": [{"product_id": overlay_id(manifest, "overlay_product"), "quantity": 1}]},
    )
    assert created.status_code == 201
    order = created.json()["order"]["id"]
    first = client.post(
        f"/v1/orders/{order}/cancel",
        headers={**primary_headers, "Idempotency-Key": idempotency_key},
    )
    assert first.status_code == 200
    different_target = client.post(
        f"/v1/orders/{scenario_id(manifest, 'order_other_customer')}/cancel",
        headers={**primary_headers, "Idempotency-Key": idempotency_key},
    )
    assert different_target.status_code == 409
    assert different_target.json()["error"]["code"] == "idempotency_key_reused"

    different_operation = client.post(
        "/v1/orders",
        headers={**primary_headers, "Idempotency-Key": idempotency_key},
        json={"items": [{"product_id": overlay_id(manifest, "overlay_product"), "quantity": 1}]},
    )
    assert different_operation.status_code == 409
    assert different_operation.json()["error"]["code"] == "idempotency_key_reused"


def test_invalid_body_and_missing_key_do_not_enter_write_executor(
    client: httpx.Client, primary_headers: dict[str, str], manifest: dict[str, object]
) -> None:
    path = "/v1/orders"
    invalid = client.post(
        path,
        headers={**primary_headers, "Idempotency-Key": "bad"},
        json={"items": []},
    )
    missing_key = client.post(
        path,
        headers=primary_headers,
        json={"items": [{"product_id": overlay_id(manifest, "overlay_product"), "quantity": 1}]},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "invalid_query"
    assert missing_key.status_code == 400
    assert missing_key.json()["error"]["code"] == "idempotency_key_required"
