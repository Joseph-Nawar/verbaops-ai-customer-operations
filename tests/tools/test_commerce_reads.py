"""Tests for normalized read handlers and trusted execution context."""

from datetime import date
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from verbaops.commerce.client import CommerceClient
from verbaops.config import CommerceSettings
from verbaops.tools.commerce_reads import (
    get_order_status,
    get_refund_status,
    get_shipment_status,
    list_delivery_slots,
    search_products,
)
from verbaops.tools.models import (
    GetOrderStatusInput,
    GetRefundStatusInput,
    GetShipmentStatusInput,
    ListDeliverySlotsInput,
    SearchProductsInput,
    ToolExecutionContext,
)


def make_client(handler: object) -> CommerceClient:
    return CommerceClient(
        CommerceSettings(
            base_url="http://commerce.internal",
            service_token=SecretStr("trusted-service-token"),
        ),
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_order_handler_uses_trusted_customer_context_and_normalizes_output() -> None:
    order_id = uuid4()
    customer_id = uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-verbaops-customer-id"] == str(customer_id)
        return httpx.Response(
            200,
            json={
                "id": str(order_id),
                "customer_id": str(customer_id),
                "status": "shipped",
                "total": "0012.3400",
                "created_at": "2026-08-24T12:00:00Z",
                "updated_at": "2026-08-24T12:00:00Z",
                "items": [],
            },
        )

    result = await get_order_status(
        GetOrderStatusInput(order_id=order_id),
        ToolExecutionContext(customer_id=customer_id),
        make_client(handler),
    )

    assert result.order_id == order_id
    assert result.status == "shipped"
    assert result.total == "0012.3400"


@pytest.mark.asyncio
async def test_other_read_handlers_return_typed_normalized_outputs() -> None:
    order_id = uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/shipment"):
            return httpx.Response(
                200,
                json={
                    "id": str(uuid4()),
                    "order_id": str(order_id),
                    "carrier": "Carrier",
                    "tracking_number": "TRACK",
                    "status": "delivered",
                    "estimated_delivery": None,
                    "delivered_at": "2026-08-24T12:00:00Z",
                    "delivery_slot_id": None,
                },
            )
        if request.url.path.endswith("/refunds"):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": str(uuid4()),
                        "amount": "0004.500",
                        "status": "completed",
                        "reason": "Damaged",
                        "requires_manual_approval": False,
                        "created_at": "2026-08-24T10:00:00Z",
                    }
                ],
            )
        if request.url.path.endswith("/products/search"):
            return httpx.Response(
                200,
                json={"items": [], "limit": 1, "offset": 0, "has_more": False},
            )
        return httpx.Response(
            200,
            json=[
                {
                    "id": str(uuid4()),
                    "service_date": "2026-08-25",
                    "window_start": "09:00:00",
                    "window_end": "11:00:00",
                    "capacity": 10,
                    "reserved_count": 2,
                    "remaining_capacity": 8,
                    "available": True,
                }
            ],
        )

    client = make_client(handler)
    context = ToolExecutionContext(customer_id=uuid4())
    shipment = await get_shipment_status(GetShipmentStatusInput(order_id=order_id), context, client)
    refunds = await get_refund_status(GetRefundStatusInput(order_id=order_id), context, client)
    products = await search_products(SearchProductsInput(query="phone", limit=1), context, client)
    slots = await list_delivery_slots(
        ListDeliverySlotsInput(
            date_from=date(2026, 8, 25), date_to=date(2026, 8, 25), available_only=True
        ),
        context,
        client,
    )

    assert shipment.shipment_id
    assert shipment.status == "delivered"
    assert refunds.refunds[0].amount == "0004.500"
    assert products.items == ()
    assert slots.slots[0].available is True
