"""Fixed-route, single-dispatch tests for the internal Commerce write boundary."""

from collections.abc import Callable
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from verbaops.commerce.client import CommerceClient
from verbaops.commerce.errors import (
    CommerceWriteAmbiguousError,
    CommerceWritePreDispatchError,
    CommerceWriteRejected,
)
from verbaops.commerce.models import (
    RefundCreateRequest,
    ReturnCreateItemRequest,
    ReturnCreateRequest,
    SupportTicketCategory,
    SupportTicketCreateRequest,
)
from verbaops.config import CommerceSettings

TOKEN = "write-client-secret-sentinel"


def client_for(handler: Callable[[httpx.Request], httpx.Response]) -> CommerceClient:
    settings = CommerceSettings(
        base_url="https://commerce.internal/api/",
        service_token=SecretStr(TOKEN),
        timeout_seconds=3,
    )
    return CommerceClient(settings, httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def order(order_id: str, customer_id: str, status: str = "cancelled") -> dict[str, Any]:
    return {
        "id": order_id,
        "customer_id": customer_id,
        "status": status,
        "total": "20.00",
        "created_at": "2026-10-01T00:00:00Z",
        "updated_at": "2026-10-01T00:00:00Z",
        "items": [],
    }


def shipment(order_id: str, slot_id: str | None = None) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "order_id": order_id,
        "carrier": "Test Carrier",
        "tracking_number": None,
        "status": "pending",
        "estimated_delivery": None,
        "delivered_at": None,
        "delivery_slot_id": slot_id,
    }


@pytest.mark.asyncio
async def test_five_write_methods_use_fixed_paths_trusted_headers_and_typed_contracts() -> None:
    customer_id, order_id, item_id, slot_id = (uuid4() for _ in range(4))
    key = uuid4()
    return_id, ticket_id, refund_id = (uuid4() for _ in range(3))
    expected: dict[str, tuple[str, str]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        assert request.headers["x-verbaops-customer-id"] == str(customer_id)
        assert request.headers["idempotency-key"] == str(key)
        path = request.url.path
        if path.endswith(f"/orders/{order_id}/cancel"):
            assert request.method == "POST" and request.content == b"{}"
            expected["cancel"] = (request.method, path)
            return httpx.Response(
                200,
                json={"order": order(str(order_id), str(customer_id)), "shipment": None},
            )
        if path.endswith(f"/orders/{order_id}/reschedule"):
            assert request.method == "POST"
            assert request.content == f'{{"delivery_slot_id":"{slot_id}"}}'.encode()
            expected["reschedule"] = (request.method, path)
            return httpx.Response(200, json=shipment(str(order_id), str(slot_id)))
        if path == "/api/v1/returns":
            assert request.method == "POST"
            assert (
                request.content
                == (
                    f'{{"order_id":"{order_id}","reason":"damaged",'
                    f'"items":[{{"order_item_id":"{item_id}","quantity":1}}]}}'
                ).encode()
            )
            expected["return"] = (request.method, path)
            return httpx.Response(
                201,
                json={
                    "id": str(return_id),
                    "order_id": str(order_id),
                    "reason": "damaged",
                    "status": "requested",
                    "created_at": "2026-10-01T00:00:00Z",
                    "updated_at": "2026-10-01T00:00:00Z",
                    "items": [{"id": str(uuid4()), "order_item_id": str(item_id), "quantity": 1}],
                },
            )
        if path == "/api/v1/support-tickets":
            assert request.method == "POST"
            assert (
                request.content
                == (
                    f'{{"order_id":"{order_id}","category":"delivery",'
                    '"subject":"Late delivery","description":"Please help"}'
                ).encode()
            )
            expected["ticket"] = (request.method, path)
            return httpx.Response(
                201,
                json={
                    "id": str(ticket_id),
                    "customer_id": str(customer_id),
                    "order_id": str(order_id),
                    "category": "delivery",
                    "subject": "Late delivery",
                    "description": "Please help",
                    "status": "open",
                    "created_at": "2026-10-01T00:00:00Z",
                    "updated_at": "2026-10-01T00:00:00Z",
                },
            )
        assert path == f"/api/v1/orders/{order_id}/refunds"
        assert request.method == "POST"
        assert request.content == (
            b'{"amount":"12.50","reason":"damaged","approval_reference":null}'
        )
        expected["refund"] = (request.method, path)
        return httpx.Response(
            201,
            json={
                "id": str(refund_id),
                "amount": "12.50",
                "status": "approved",
                "reason": "damaged",
                "requires_manual_approval": False,
                "created_at": "2026-10-01T00:00:00Z",
            },
        )

    commerce = client_for(handler)
    async with commerce._http_client:
        cancelled = await commerce.cancel_order(order_id, customer_id, key)
        rescheduled = await commerce.reschedule_delivery(order_id, customer_id, slot_id, key)
        created_return = await commerce.create_return(
            customer_id,
            ReturnCreateRequest(
                order_id=order_id,
                reason="damaged",
                items=[ReturnCreateItemRequest(order_item_id=item_id, quantity=1)],
            ),
            key,
        )
        created_ticket = await commerce.create_support_ticket(
            customer_id,
            SupportTicketCreateRequest(
                order_id=order_id,
                category=SupportTicketCategory.DELIVERY,
                subject="Late delivery",
                description="Please help",
            ),
            key,
        )
        created_refund = await commerce.request_refund(
            order_id,
            customer_id,
            RefundCreateRequest(amount=Decimal("12.50"), reason="damaged"),
            None,
            key,
        )

    assert cancelled.response.order.id == order_id
    assert cancelled.response.shipment is None
    assert rescheduled.response.order_id == order_id
    assert created_return.response.id == return_id
    assert created_ticket.response.customer_id == customer_id
    assert created_refund.response.id == refund_id
    assert all(
        not result.replayed
        for result in (cancelled, rescheduled, created_return, created_ticket, created_refund)
    )
    assert expected == {
        "cancel": ("POST", f"/api/v1/orders/{order_id}/cancel"),
        "reschedule": ("POST", f"/api/v1/orders/{order_id}/reschedule"),
        "return": ("POST", "/api/v1/returns"),
        "ticket": ("POST", "/api/v1/support-tickets"),
        "refund": ("POST", f"/api/v1/orders/{order_id}/refunds"),
    }


@pytest.mark.asyncio
async def test_exact_return_and_ticket_reads_are_customer_scoped() -> None:
    customer_id, order_id = uuid4(), uuid4()
    return_id, ticket_id = uuid4(), uuid4()
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        assert request.headers["x-verbaops-customer-id"] == str(customer_id)
        seen.append(request.url.path)
        if request.url.path.endswith(str(return_id)):
            return httpx.Response(
                200,
                json={
                    "id": str(return_id),
                    "order_id": str(order_id),
                    "reason": "damaged",
                    "status": "requested",
                    "created_at": "2026-10-01T00:00:00Z",
                    "updated_at": "2026-10-01T00:00:00Z",
                    "items": [],
                },
            )
        assert request.url.path == f"/api/v1/support-tickets/{ticket_id}"
        return httpx.Response(
            200,
            json={
                "id": str(ticket_id),
                "customer_id": str(customer_id),
                "order_id": str(order_id),
                "category": "delivery",
                "subject": "Late delivery",
                "description": "Please help",
                "status": "open",
                "created_at": "2026-10-01T00:00:00Z",
                "updated_at": "2026-10-01T00:00:00Z",
            },
        )

    commerce = client_for(handler)
    async with commerce._http_client:
        found_return = await commerce.get_return(return_id, customer_id)
        found_ticket = await commerce.get_support_ticket(ticket_id, customer_id)

    assert found_return.id == return_id
    assert found_ticket.id == ticket_id
    assert seen == [
        f"/api/v1/returns/{return_id}",
        f"/api/v1/support-tickets/{ticket_id}",
    ]


@pytest.mark.asyncio
async def test_write_client_does_not_retry_or_accept_arbitrary_routes() -> None:
    customer_id, order_id, key = uuid4(), uuid4(), uuid4()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectTimeout("private transport detail")

    commerce = client_for(handler)
    async with commerce._http_client:
        with pytest.raises(CommerceWritePreDispatchError) as raised:
            await commerce.cancel_order(order_id, customer_id, key)

    assert calls == 1
    assert "private transport detail" not in repr(raised.value)
    assert not hasattr(commerce, "request")
    assert not hasattr(commerce, "write")


@pytest.mark.asyncio
async def test_known_business_rejection_is_typed_and_keeps_only_bounded_code() -> None:
    customer_id, order_id, key = uuid4(), uuid4(), uuid4()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            409,
            json={"error": {"code": "order_not_cancellable", "message": "do not retain"}},
        )

    commerce = client_for(handler)
    async with commerce._http_client:
        with pytest.raises(CommerceWriteRejected) as raised:
            await commerce.cancel_order(order_id, customer_id, key)

    assert calls == 1
    assert raised.value.status_code == 409
    assert raised.value.error_code == "order_not_cancellable"
    assert "do not retain" not in repr(raised.value)
    assert TOKEN not in repr(raised.value)


@pytest.mark.asyncio
async def test_unsafe_upstream_error_code_is_not_retained() -> None:
    customer_id, order_id, key = uuid4(), uuid4(), uuid4()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            json={
                "error": {
                    "code": "bad code with\nprivate detail",
                    "message": "do not retain",
                }
            },
        )

    commerce = client_for(handler)
    async with commerce._http_client:
        with pytest.raises(CommerceWriteRejected) as raised:
            await commerce.cancel_order(order_id, customer_id, key)

    assert raised.value.error_code is None
    assert "private detail" not in repr(raised.value)
    assert "do not retain" not in repr(raised.value)


@pytest.mark.asyncio
async def test_unknown_outcome_and_malformed_success_are_ambiguous_single_dispatches() -> None:
    customer_id, order_id, key = uuid4(), uuid4(), uuid4()
    for response in (
        httpx.Response(503, json={"error": {"code": "write_outcome_unknown"}}),
        httpx.Response(200, json={"order": {"id": str(order_id)}, "shipment": None}),
    ):
        calls = 0

        def handler(_request: httpx.Request, response: httpx.Response = response) -> httpx.Response:
            nonlocal calls
            calls += 1
            return response

        commerce = client_for(handler)
        async with commerce._http_client:
            with pytest.raises(CommerceWriteAmbiguousError):
                await commerce.cancel_order(order_id, customer_id, key)
        assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected_error"),
    [
        (httpx.ReadTimeout("read timed out"), CommerceWriteAmbiguousError),
        (httpx.WriteTimeout("write timed out"), CommerceWriteAmbiguousError),
        (httpx.RemoteProtocolError("remote reset"), CommerceWriteAmbiguousError),
        (httpx.ConnectError("connect failed"), CommerceWritePreDispatchError),
        (httpx.PoolTimeout("pool unavailable"), CommerceWritePreDispatchError),
    ],
)
async def test_transport_failure_classification_is_single_dispatch(
    failure: httpx.TransportError,
    expected_error: type[Exception],
) -> None:
    customer_id, order_id, key = uuid4(), uuid4(), uuid4()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise failure

    commerce = client_for(handler)
    async with commerce._http_client:
        with pytest.raises(expected_error):
            await commerce.cancel_order(order_id, customer_id, key)
    assert calls == 1


def test_request_models_exclude_supervisor_approval_material() -> None:
    refund = RefundCreateRequest(amount=Decimal("50.00"), reason="customer request")
    assert "approval_reference" not in refund.model_dump(mode="json")
    assert not hasattr(refund, "action_request_id")


@pytest.mark.asyncio
async def test_refund_write_client_rejects_supervisor_evidence() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(201, json={})

    commerce = client_for(handler)
    async with commerce._http_client:
        with pytest.raises(ValueError, match="cannot carry supervisor approval evidence"):
            await commerce.request_refund(
                uuid4(),
                uuid4(),
                RefundCreateRequest(amount=Decimal("50.00"), reason="request"),
                cast(None, object()),
                uuid4(),
            )
    assert calls == 0
