"""Behavioral tests for the authenticated VerbaOps Commerce client."""

from collections.abc import Callable
from datetime import date
from typing import Any
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from verbaops.commerce.client import CommerceClient
from verbaops.commerce.errors import (
    CommerceAuthenticationError,
    CommerceNotFoundError,
    CommerceProtocolError,
    CommerceTimeoutError,
    CommerceUnavailableError,
)
from verbaops.commerce.models import (
    DeliverySlotResponse,
    OrderResponse,
    ProductSearchResponse,
    RefundResponse,
    ShipmentResponse,
)
from verbaops.config import CommerceSettings

SENTINEL_TOKEN = "sentinel-commerce-token-do-not-leak"
SENSITIVE_BODY = (
    "Authorization: Bearer sentinel-commerce-token-do-not-leak; "
    "raw backend body; https://user:sentinel-commerce-token-do-not-leak@example"
)


def make_settings() -> CommerceSettings:
    return CommerceSettings(
        base_url="https://commerce.internal/api/",
        service_token=SecretStr(SENTINEL_TOKEN),
        timeout_seconds=2.5,
    )


def make_client(handler: Callable[[httpx.Request], httpx.Response]) -> CommerceClient:
    return CommerceClient(
        make_settings(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def assert_safe(value: object) -> None:
    rendered = f"{value!s} {value!r}"
    for forbidden in (
        SENTINEL_TOKEN,
        "Authorization",
        "raw backend body",
        "https://user:sentinel-commerce-token-do-not-leak@example",
    ):
        assert forbidden not in rendered


def order_payload(order_id: str, customer_id: str) -> dict[str, Any]:
    return {
        "id": order_id,
        "customer_id": customer_id,
        "status": "confirmed",
        "total": "0012.3400",
        "created_at": "2026-08-24T12:00:00Z",
        "updated_at": "2026-08-24T12:00:00Z",
        "items": [],
    }


def shipment_payload(order_id: str) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "order_id": order_id,
        "carrier": "Carrier",
        "tracking_number": "TRACK-1",
        "status": "in_transit",
        "estimated_delivery": "2026-08-25T10:00:00Z",
        "delivered_at": None,
        "delivery_slot_id": None,
    }


def refund_payload() -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "amount": "0004.500",
        "status": "completed",
        "reason": "Damaged",
        "requires_manual_approval": False,
        "created_at": "2026-08-24T10:00:00Z",
    }


def product_search_payload() -> dict[str, Any]:
    return {"items": [], "limit": 2, "offset": 0, "has_more": False}


def slot_payload() -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "service_date": "2026-08-25",
        "window_start": "09:00:00",
        "window_end": "11:00:00",
        "capacity": 10,
        "reserved_count": 2,
        "remaining_capacity": 8,
        "available": True,
    }


@pytest.mark.asyncio
async def test_client_constructs_exact_authenticated_customer_scoped_requests() -> None:
    order_id = uuid4()
    customer_id = uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert str(request.url) == f"https://commerce.internal/api/v1/orders/{order_id}"
        assert request.headers["authorization"] == f"Bearer {SENTINEL_TOKEN}"
        assert request.headers["x-verbaops-customer-id"] == str(customer_id)
        return httpx.Response(200, json=order_payload(str(order_id), str(customer_id)))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        response = await CommerceClient(make_settings(), http_client).get_order(
            order_id, customer_id
        )

    assert isinstance(response, OrderResponse)
    assert response.total == "0012.3400"


@pytest.mark.asyncio
async def test_client_constructs_exact_paths_queries_and_headers_for_all_reads() -> None:
    order_id = uuid4()
    customer_id = uuid4()
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        assert request.headers["authorization"] == f"Bearer {SENTINEL_TOKEN}"
        if request.url.path.endswith("/shipment"):
            assert request.headers["x-verbaops-customer-id"] == str(customer_id)
            return httpx.Response(200, json=shipment_payload(str(order_id)))
        if request.url.path.endswith("/refunds"):
            assert request.headers["x-verbaops-customer-id"] == str(customer_id)
            return httpx.Response(200, json=[refund_payload()])
        if request.url.path.endswith("/products/search"):
            assert "x-verbaops-customer-id" not in request.headers
            assert dict(request.url.params) == {"q": "phone", "limit": "2", "offset": "0"}
            return httpx.Response(200, json=product_search_payload())
        assert request.url.path == "/api/v1/delivery-slots"
        assert "x-verbaops-customer-id" not in request.headers
        assert dict(request.url.params) == {
            "from_date": "2026-08-25",
            "to_date": "2026-08-26",
            "available_only": "true",
        }
        return httpx.Response(200, json=[slot_payload()])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = CommerceClient(make_settings(), http_client)
        shipment = await client.get_shipment(order_id, customer_id)
        refunds = await client.get_refunds(order_id, customer_id)
        products = await client.search_products("phone", 2)
        slots = await client.list_delivery_slots(date(2026, 8, 25), date(2026, 8, 26), True)

    assert isinstance(shipment, ShipmentResponse)
    assert len(refunds) == 1 and isinstance(refunds[0], RefundResponse)
    assert isinstance(products, ProductSearchResponse)
    assert len(slots) == 1 and isinstance(slots[0], DeliverySlotResponse)
    assert calls == [
        f"https://commerce.internal/api/v1/orders/{order_id}/shipment",
        f"https://commerce.internal/api/v1/orders/{order_id}/refunds",
        "https://commerce.internal/api/v1/products/search?q=phone&limit=2&offset=0",
        "https://commerce.internal/api/v1/delivery-slots?from_date=2026-08-25&to_date=2026-08-26&available_only=true",
    ]


@pytest.mark.asyncio
async def test_sequential_reads_reuse_injected_client_without_client_owned_close() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=product_search_payload())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = CommerceClient(make_settings(), http_client)
        await client.search_products("first", 1)
        await client.search_products("second", 1)
        assert client._http_client is http_client
        assert http_client.is_closed is False
        assert calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [
        (401, CommerceAuthenticationError),
        (403, CommerceAuthenticationError),
        (404, CommerceNotFoundError),
        (429, CommerceUnavailableError),
        (400, CommerceProtocolError),
        (422, CommerceProtocolError),
    ],
)
async def test_http_status_failures_map_to_safe_typed_errors(
    status_code: int, error_type: type[Exception]
) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status_code, content=SENSITIVE_BODY.encode())

    with pytest.raises(error_type) as error:
        await make_client(handler).search_products("phone", 1)

    assert calls == 1
    assert_safe(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [502, 503, 504])
async def test_retryable_status_failure_is_retried_once(status_code: int) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(status_code, content=SENSITIVE_BODY.encode())
        return httpx.Response(200, json=product_search_payload())

    response = await make_client(handler).search_products("phone", 1)

    assert response.items == []
    assert calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("transport_error", "error_type"),
    [
        (httpx.TimeoutException(SENSITIVE_BODY), CommerceTimeoutError),
        (httpx.ConnectError(SENSITIVE_BODY), CommerceUnavailableError),
    ],
)
async def test_retryable_transport_failure_is_retried_once(
    transport_error: httpx.HTTPError, error_type: type[Exception]
) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise transport_error
        return httpx.Response(200, json=product_search_payload())

    response = await make_client(handler).search_products("phone", 1)

    assert response.items == []
    assert calls == 2


@pytest.mark.asyncio
async def test_exhausted_timeout_and_connection_failures_keep_typed_errors() -> None:
    for transport_error, error_type in (
        (httpx.TimeoutException(SENSITIVE_BODY), CommerceTimeoutError),
        (httpx.ConnectError(SENSITIVE_BODY), CommerceUnavailableError),
    ):
        calls = 0

        def handler(
            _request: httpx.Request,
            transport_error: httpx.HTTPError = transport_error,
        ) -> httpx.Response:
            nonlocal calls
            calls += 1
            raise transport_error

        with pytest.raises(error_type) as error:
            await make_client(handler).search_products("phone", 1)
        assert calls == 2
        assert_safe(error.value)


@pytest.mark.asyncio
async def test_invalid_json_and_schema_are_protocol_errors_without_raw_body() -> None:
    for response in (
        httpx.Response(200, content=b"{not-json"),
        httpx.Response(200, json={"unexpected": True}),
    ):

        def handler(_request: httpx.Request, response: httpx.Response = response) -> httpx.Response:
            return response

        with pytest.raises(CommerceProtocolError) as error:
            await make_client(handler).search_products("phone", 1)
        assert_safe(error.value)


def test_public_commerce_client_and_settings_redact_secrets() -> None:
    client = make_client(lambda _request: httpx.Response(200, json=product_search_payload()))

    assert_safe(make_settings())
    assert_safe(client)
