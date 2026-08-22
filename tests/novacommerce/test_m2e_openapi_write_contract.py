"""Raw OpenAPI contract tests for the M2E write surface."""

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from pydantic import SecretStr
from scripts.normalize_openapi import normalize_openapi

from novacommerce.api.app import create_app
from novacommerce.config.settings import Environment, Settings
from novacommerce.db.models.refund import RefundStatus
from novacommerce.schemas.writes import WriteRefundResponse


def raw_openapi() -> dict[str, Any]:
    app = create_app(
        settings=Settings(
            environment=Environment.TEST,
            service_token=SecretStr("m2e-openapi-test-token-" + "x" * 32),
        )
    )
    return app.openapi()


def operation(spec: Mapping[str, Any], path: str, method: str) -> Mapping[str, Any]:
    return cast(Mapping[str, Any], spec["paths"][path][method])


def header_parameter(operation_spec: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    return next(
        parameter
        for parameter in operation_spec.get("parameters", [])
        if parameter["in"] == "header" and parameter["name"] == name
    )


def test_raw_openapi_documents_write_success_status_and_response_models() -> None:
    spec = raw_openapi()
    expected = {
        ("/v1/orders", "post"): ("201", "CreateOrderResponse"),
        ("/v1/orders/{order_id}/cancel", "post"): ("200", "CancelOrderResponse"),
        ("/v1/orders/{order_id}/reschedule", "post"): ("200", "ShipmentResponse"),
        ("/v1/returns", "post"): ("201", "ReturnResponse"),
        ("/v1/orders/{order_id}/refunds", "post"): ("201", "WriteRefundResponse"),
        ("/v1/support-tickets", "post"): ("201", "SupportTicketResponse"),
    }

    for (path, method), (status, schema_name) in expected.items():
        response = operation(spec, path, method)["responses"][status]
        assert response["content"]["application/json"]["schema"] == {
            "$ref": f"#/components/schemas/{schema_name}"
        }


def test_raw_openapi_documents_customer_and_idempotency_headers_as_required() -> None:
    spec = raw_openapi()
    customer_paths = {
        "/v1/customers/{customer_id}",
        "/v1/orders/{order_id}",
        "/v1/orders/{order_id}/shipment",
        "/v1/orders/{order_id}/refunds",
        "/v1/orders",
        "/v1/orders/{order_id}/cancel",
        "/v1/orders/{order_id}/reschedule",
        "/v1/returns",
        "/v1/support-tickets",
    }
    write_paths = {
        "/v1/orders",
        "/v1/orders/{order_id}/cancel",
        "/v1/orders/{order_id}/reschedule",
        "/v1/returns",
        "/v1/orders/{order_id}/refunds",
        "/v1/support-tickets",
    }

    for path in customer_paths:
        method = "post" if path in write_paths else "get"
        assert (
            header_parameter(operation(spec, path, method), "X-VerbaOps-Customer-ID")["required"]
            is True
        )

    for path in write_paths:
        assert (
            header_parameter(operation(spec, path, "post"), "Idempotency-Key")["required"] is True
        )

    for path in ("/v1/products/search", "/v1/delivery-slots"):
        assert not any(
            parameter.get("name") == "X-VerbaOps-Customer-ID"
            for parameter in operation(spec, path, "get").get("parameters", [])
        )


def test_raw_openapi_preserves_precise_response_field_schemas() -> None:
    schemas = raw_openapi()["components"]["schemas"]

    order = schemas["OrderResponse"]["properties"]
    assert order["id"] == {"type": "string", "format": "uuid", "title": "Id"}
    assert order["customer_id"]["format"] == "uuid"
    assert order["status"].get("$ref") or order["status"].get("enum")
    assert order["total"]["type"] == "string"
    assert "pattern" in order["total"]
    assert order["created_at"] == {
        "type": "string",
        "format": "date-time",
        "title": "Created At",
    }
    assert order["items"]["items"] == {"$ref": "#/components/schemas/OrderItemResponse"}

    shipment = schemas["ShipmentResponse"]["properties"]
    assert shipment["id"]["format"] == "uuid"
    assert shipment["order_id"]["format"] == "uuid"

    refund = schemas["RefundResponse"]["properties"]
    assert refund["id"]["format"] == "uuid"
    assert refund["amount"]["type"] == "string"
    assert "pattern" in refund["amount"]
    assert refund["requires_manual_approval"]["type"] == "boolean"
    assert refund["created_at"]["format"] == "date-time"

    product_search = schemas["ProductSearchResponse"]["properties"]
    assert product_search["items"]["items"] == {"$ref": "#/components/schemas/ProductResponse"}

    slot = schemas["DeliverySlotResponse"]["properties"]
    assert slot["capacity"]["type"] == "integer"
    assert slot["reserved_count"]["type"] == "integer"
    assert slot["remaining_capacity"]["type"] == "integer"
    assert slot["available"]["type"] == "boolean"
    assert slot["service_date"]["format"] == "date"
    assert slot["window_start"]["format"] == "time"
    assert slot["window_end"]["format"] == "time"


def test_normalized_schema_preserves_real_description_property() -> None:
    spec = raw_openapi()
    normalized = normalize_openapi(spec)
    ticket = normalized["components"]["schemas"]["SupportTicketCreateRequest"]

    assert "description" in ticket["properties"]
    assert ticket["properties"]["description"]["type"] == "string"
    assert ticket["properties"]["description"]["maxLength"] == 5000
    assert ticket["required"] == ["subject", "description"]
    assert "description" not in operation(spec, "/v1/support-tickets", "post")


def test_raw_write_operations_require_service_bearer_security() -> None:
    spec = raw_openapi()
    for path, methods in spec["paths"].items():
        if path.startswith("/v1"):
            for method, operation_spec in methods.items():
                if method in {"get", "post"}:
                    assert {"NovaCommerceServiceBearer": []} in operation_spec["security"]


def test_raw_and_normalized_write_contracts_share_critical_semantics() -> None:
    raw = raw_openapi()
    normalized = normalize_openapi(raw)
    for path in (
        "/v1/orders",
        "/v1/orders/{order_id}/cancel",
        "/v1/orders/{order_id}/reschedule",
        "/v1/returns",
        "/v1/orders/{order_id}/refunds",
        "/v1/support-tickets",
    ):
        raw_operation = operation(raw, path, "post")
        normalized_operation = operation(normalized, path, "post")
        assert set(raw_operation["responses"]) == set(normalized_operation["responses"])
        assert raw_operation["security"] == normalized_operation["security"]
        assert header_parameter(raw_operation, "Idempotency-Key")["required"] is True
        assert header_parameter(normalized_operation, "Idempotency-Key")["required"] is True


def test_decimal_wire_serialization_remains_an_exact_string() -> None:
    response = WriteRefundResponse(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        amount=Decimal("500.00"),
        status=RefundStatus.APPROVED,
        reason="approved",
        requires_manual_approval=False,
        created_at=datetime(2026, 8, 21, tzinfo=UTC),
    )

    assert response.model_dump(mode="json")["amount"] == "500.00"
    assert '"amount":"500.00"' in response.model_dump_json()
