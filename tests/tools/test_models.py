"""Tests for strict model-visible inputs and normalized tool outputs."""

from datetime import date
from uuid import uuid4

import pytest
from pydantic import ValidationError

from verbaops.tools.models import (
    GetOrderStatusInput,
    GetShipmentStatusInput,
    ListDeliverySlotsInput,
    SearchProductsInput,
    ToolExecutionContext,
)


def test_customer_scoped_inputs_accept_only_resource_identifiers() -> None:
    order_id = uuid4()

    assert GetOrderStatusInput(order_id=order_id).order_id == order_id
    assert GetShipmentStatusInput(order_id=order_id).order_id == order_id


@pytest.mark.parametrize("model", [GetOrderStatusInput, GetShipmentStatusInput])
def test_customer_scoped_inputs_reject_identity_and_extra_fields(model: type[object]) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({"order_id": str(uuid4()), "customer_id": str(uuid4())})  # type: ignore[attr-defined]


@pytest.mark.parametrize("query", ["", "   ", "x" * 101])
def test_search_products_rejects_blank_or_oversized_queries(query: str) -> None:
    with pytest.raises(ValidationError):
        SearchProductsInput(query=query, limit=1)


@pytest.mark.parametrize("limit", [0, 11])
def test_search_products_limits_are_bounded(limit: int) -> None:
    with pytest.raises(ValidationError):
        SearchProductsInput(query="phone", limit=limit)


def test_search_products_strips_query_whitespace() -> None:
    assert SearchProductsInput(query="  phone  ", limit=1).query == "phone"


def test_delivery_slots_require_ordered_bounded_dates() -> None:
    with pytest.raises(ValidationError):
        ListDeliverySlotsInput(
            date_from=date(2026, 8, 26),
            date_to=date(2026, 8, 25),
            available_only=True,
        )
    with pytest.raises(ValidationError):
        ListDeliverySlotsInput(
            date_from=date(2026, 8, 1),
            date_to=date(2026, 10, 1),
            available_only=True,
        )


def test_execution_context_is_frozen_and_contains_only_trusted_customer_scope() -> None:
    context = ToolExecutionContext(customer_id=uuid4())

    assert set(context.model_dump()) == {"customer_id"}
    with pytest.raises(ValidationError):
        context.customer_id = uuid4()
