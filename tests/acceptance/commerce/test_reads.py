"""Read-only customer and catalog contracts over HTTP."""

from decimal import Decimal

import httpx

from .conftest import overlay_id, scenario_id


def test_customer_order_shipment_and_refund_reads(
    client: httpx.Client, primary_headers: dict[str, str], manifest: dict[str, object]
) -> None:
    primary = scenario_id(manifest, "customer_primary")
    order = scenario_id(manifest, "order_cancellable")
    response = client.get(f"/v1/customers/{primary}", headers=primary_headers)
    assert response.status_code == 200
    assert response.json()["id"] == primary

    order_response = client.get(f"/v1/orders/{order}", headers=primary_headers)
    assert order_response.status_code == 200
    payload = order_response.json()
    assert payload["id"] == order
    assert payload["items"]
    assert all("line_total" in item for item in payload["items"])
    assert Decimal(payload["total"]) == sum(
        (Decimal(item["line_total"]) for item in payload["items"]), Decimal("0.00")
    )

    shipment = client.get(f"/v1/orders/{order}/shipment", headers=primary_headers)
    assert shipment.status_code == 200
    assert shipment.json()["order_id"] == order
    assert client.get(f"/v1/orders/{order}/refunds", headers=primary_headers).json() == []


def test_product_search_is_case_insensitive_paginated_and_literal_safe(
    client: httpx.Client, authenticated_headers: dict[str, str]
) -> None:
    response = client.get(
        "/v1/products/search",
        headers=authenticated_headers,
        params={"q": "ACCEPTANCE-OVERLAY", "limit": 1, "offset": 0},
    )
    assert response.status_code == 200
    assert response.json()["items"]
    assert response.json()["has_more"] is False
    hostile = client.get(
        "/v1/products/search", headers=authenticated_headers, params={"q": "%_" + chr(92)}
    )
    assert hostile.status_code == 200
    assert hostile.json()["items"] == []


def test_delivery_slot_reads_derive_availability(
    client: httpx.Client, authenticated_headers: dict[str, str], manifest: dict[str, object]
) -> None:
    response = client.get(
        "/v1/delivery-slots",
        headers=authenticated_headers,
        params={"from_date": "2026-08-21", "to_date": "2026-09-20", "available_only": "false"},
    )
    assert response.status_code == 200
    by_id = {item["id"]: item for item in response.json()}
    for name, remaining, available in (
        ("slot_available", 15, True),
        ("slot_one_remaining", 1, True),
        ("slot_full", 0, False),
    ):
        slot = by_id[scenario_id(manifest, name)]
        assert slot["capacity"] == 20
        assert slot["remaining_capacity"] == remaining
        assert slot["available"] is available

    only_available = client.get(
        "/v1/delivery-slots", headers=authenticated_headers, params={"available_only": "true"}
    )
    assert scenario_id(manifest, "slot_full") not in {item["id"] for item in only_available.json()}


def test_overlay_reschedulable_resources_are_reachable(
    client: httpx.Client, primary_headers: dict[str, str], manifest: dict[str, object]
) -> None:
    order = overlay_id(manifest, "reschedulable_order")
    shipment = client.get(f"/v1/orders/{order}/shipment", headers=primary_headers)
    assert shipment.status_code == 200
    assert shipment.json()["id"] == overlay_id(manifest, "reschedulable_shipment")
