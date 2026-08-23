"""M2E exact business-route contract checks."""

from fastapi import FastAPI
from pydantic import SecretStr

from novacommerce.api.app import create_app
from novacommerce.config.settings import Environment, Settings

EXPECTED_BUSINESS_ROUTES = {
    ("GET", "/v1/customers/{customer_id}"),
    ("GET", "/v1/orders/{order_id}"),
    ("GET", "/v1/orders/{order_id}/shipment"),
    ("GET", "/v1/orders/{order_id}/refunds"),
    ("GET", "/v1/products/search"),
    ("GET", "/v1/delivery-slots"),
    ("POST", "/v1/orders"),
    ("POST", "/v1/orders/{order_id}/cancel"),
    ("POST", "/v1/orders/{order_id}/reschedule"),
    ("POST", "/v1/returns"),
    ("POST", "/v1/orders/{order_id}/refunds"),
    ("POST", "/v1/support-tickets"),
}


def business_route_set(app: FastAPI) -> set[tuple[str, str]]:
    return {
        (method.upper(), path)
        for path, path_item in app.openapi()["paths"].items()
        if path.startswith("/v1")
        for method in path_item
        if method in {"get", "post", "put", "patch", "delete"}
    }


def test_m2e_business_route_set_is_exactly_the_reviewed_twelve_operations() -> None:
    app = create_app(
        settings=Settings(
            environment=Environment.TEST,
            service_token=SecretStr("m2e-route-contract-token-" + "x" * 32),
        )
    )

    assert business_route_set(app) == EXPECTED_BUSINESS_ROUTES


def test_m2e_operational_routes_are_outside_business_route_set() -> None:
    app = create_app(
        settings=Settings(
            environment=Environment.TEST,
            service_token=SecretStr("m2e-route-contract-token-" + "x" * 32),
        )
    )

    operational_paths = {"/health", "/ready", "/version", "/docs", "/openapi.json"}
    assert operational_paths.intersection(app.openapi()["paths"]) == {
        "/health",
        "/ready",
        "/version",
    }
    assert all(not path.startswith("/v1") for path in operational_paths)
