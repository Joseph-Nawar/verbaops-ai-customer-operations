"""Operational health and exact public contract checks over HTTP."""

import hashlib
from pathlib import Path

import httpx
from scripts.openapi_contract import normalized_bytes


def test_operational_endpoints_are_healthy(client: httpx.Client) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").status_code == 200
    version = client.get("/version")
    assert version.status_code == 200
    assert version.json()["service"] == "novacommerce"


def test_openapi_is_exact_locked_contract(client: httpx.Client) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    actual = normalized_bytes(response.json())
    expected_path = Path(__file__).parents[3] / "contracts" / "novacommerce-openapi.json"
    expected = expected_path.read_bytes()
    assert hashlib.sha256(actual).hexdigest().upper() == (
        "3BF079B4222725FC507DB67B3BCC6009DF0941FAC201A0370D2F15F1FC6AE487"
    )
    assert actual == expected


def test_openapi_has_exactly_nine_get_and_six_post_business_routes(client: httpx.Client) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    expected = {
        ("GET", "/v1/customers/{customer_id}"),
        ("GET", "/v1/orders/{order_id}"),
        ("GET", "/v1/orders/{order_id}/shipment"),
        ("GET", "/v1/orders/{order_id}/refunds"),
        ("GET", "/v1/products/search"),
        ("GET", "/v1/delivery-slots"),
        ("GET", "/v1/returns/{return_id}"),
        ("GET", "/v1/support-tickets/{ticket_id}"),
        ("GET", "/v1/tenant-config/currency"),
        ("POST", "/v1/orders"),
        ("POST", "/v1/orders/{order_id}/cancel"),
        ("POST", "/v1/orders/{order_id}/reschedule"),
        ("POST", "/v1/returns"),
        ("POST", "/v1/orders/{order_id}/refunds"),
        ("POST", "/v1/support-tickets"),
    }
    actual = {(method.upper(), path) for path, item in paths.items() for method in item}
    assert {(method, path) for method, path in actual if path.startswith("/v1")} == expected
