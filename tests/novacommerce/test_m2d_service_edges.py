"""Unit coverage for transactional service boundaries before database mutation."""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest

from novacommerce.db.models.order import OrderStatus
from novacommerce.schemas.writes import (
    OrderCreateItemRequest,
    OrderCreateRequest,
    RefundCreateRequest,
    RescheduleRequest,
    ReturnCreateItemRequest,
    ReturnCreateRequest,
    SupportTicketCreateRequest,
)
from novacommerce.services.writes.orders import cancel_order, create_order
from novacommerce.services.writes.refunds import create_refund
from novacommerce.services.writes.reschedule import reschedule_shipment
from novacommerce.services.writes.returns import create_return
from novacommerce.services.writes.tickets import create_ticket

CUSTOMER = UUID("00000000-0000-0000-0000-000000000001")
ORDER = UUID("00000000-0000-0000-0000-000000000002")
PRODUCT = UUID("00000000-0000-0000-0000-000000000003")
SLOT = UUID("00000000-0000-0000-0000-000000000004")


class Result:
    def __init__(self, *, one: Any = None, rows: list[Any] | None = None) -> None:
        self.one = one
        self.rows = rows or []

    def scalar_one_or_none(self) -> Any:
        return self.one

    def scalars(self) -> "Result":
        return self

    def __iter__(self) -> Any:
        return iter(self.rows)


class Session:
    def __init__(self, *results: Result) -> None:
        self.results = list(results)

    async def execute(self, statement: Any, params: Any = None) -> Result:
        del statement, params
        return self.results.pop(0)

    async def flush(self) -> None:
        return None

    def add(self, value: Any) -> None:
        del value


@pytest.mark.asyncio
async def test_create_order_rejects_missing_and_inactive_products_before_mutation() -> None:
    missing = await create_order(
        cast(Any, Session(Result(rows=[]))),
        customer_id=CUSTOMER,
        request=OrderCreateRequest(items=[OrderCreateItemRequest(product_id=PRODUCT, quantity=1)]),
        idempotency_key="m2d-edge-create-1",
    )
    assert missing.status_code == 409
    assert missing.body["error"]["code"] == "product_unavailable"

    inactive_product = SimpleNamespace(id=PRODUCT, active=False, stock=10, price=Decimal("3.00"))
    inactive = await create_order(
        cast(Any, Session(Result(rows=[inactive_product]))),
        customer_id=CUSTOMER,
        request=OrderCreateRequest(items=[OrderCreateItemRequest(product_id=PRODUCT, quantity=1)]),
        idempotency_key="m2d-edge-create-2",
    )
    assert inactive.status_code == 409
    assert inactive.body["error"]["code"] == "product_unavailable"


@pytest.mark.asyncio
async def test_order_commands_hide_missing_owned_rows() -> None:
    cancelled = await cancel_order(
        cast(Any, Session(Result(one=None))),
        customer_id=CUSTOMER,
        order_id=ORDER,
        idempotency_key="m2d-edge-cancel-1",
    )
    assert cancelled.status_code == 404

    rescheduled = await reschedule_shipment(
        cast(Any, Session(Result(one=None))),
        customer_id=CUSTOMER,
        order_id=ORDER,
        request=RescheduleRequest(delivery_slot_id=SLOT),
        idempotency_key="m2d-edge-reschedule-1",
    )
    assert rescheduled.status_code == 404

    pending_order = SimpleNamespace(
        id=ORDER,
        customer_id=CUSTOMER,
        status=OrderStatus.PENDING,
        total=Decimal("0.00"),
        created_at=datetime(2026, 8, 21, 12, tzinfo=UTC),
        updated_at=datetime(2026, 8, 21, 12, tzinfo=UTC),
        cancelled_at=None,
    )
    cancelled_pending = await cancel_order(
        cast(
            Any,
            Session(Result(one=pending_order), Result(one=None), Result(rows=[]), Result(rows=[])),
        ),
        customer_id=CUSTOMER,
        order_id=ORDER,
        idempotency_key="m2d-edge-cancel-2",
    )
    assert cancelled_pending.status_code == 200


@pytest.mark.asyncio
async def test_return_refund_and_ticket_commands_hide_missing_owned_rows() -> None:
    item = ReturnCreateItemRequest(order_item_id=PRODUCT, quantity=1)
    returned = await create_return(
        cast(Any, Session(Result(one=None))),
        customer_id=CUSTOMER,
        request=ReturnCreateRequest(order_id=ORDER, reason="reason", items=[item]),
        idempotency_key="m2d-edge-return-1",
    )
    assert returned.status_code == 404

    refund = await create_refund(
        cast(Any, Session(Result(one=None))),
        customer_id=CUSTOMER,
        order_id=ORDER,
        request=RefundCreateRequest(amount=Decimal("1.00"), reason="reason"),
        idempotency_key="m2d-edge-refund-1",
    )
    assert refund.status_code == 404

    ticket = await create_ticket(
        cast(Any, Session(Result(one=None))),
        customer_id=CUSTOMER,
        request=SupportTicketCreateRequest(
            order_id=ORDER, subject="subject", description="description"
        ),
        idempotency_key="m2d-edge-ticket-1",
    )
    assert ticket.status_code == 404

    pending_order = SimpleNamespace(status=OrderStatus.PENDING)
    refund_pending = await create_refund(
        cast(Any, Session(Result(one=pending_order))),
        customer_id=CUSTOMER,
        order_id=ORDER,
        request=RefundCreateRequest(amount=Decimal("1.00"), reason="reason"),
        idempotency_key="m2d-edge-refund-2",
    )
    assert refund_pending.body["error"]["code"] == "refund_not_allowed"


def test_write_request_bounds_and_forbid_client_owned_fields() -> None:
    with pytest.raises(ValueError):
        OrderCreateRequest(items=[])
    with pytest.raises(ValueError):
        OrderCreateRequest.model_validate(
            {"items": [{"product_id": str(PRODUCT), "quantity": 1}], "status": "shipped"}
        )
    with pytest.raises(ValueError):
        SupportTicketCreateRequest(subject=" ", description="description")
    with pytest.raises(ValueError):
        RefundCreateRequest(amount=Decimal("0.00"), reason="reason")
