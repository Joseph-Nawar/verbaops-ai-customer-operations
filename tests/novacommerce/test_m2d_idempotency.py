"""Pure M2D idempotency contracts."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from pydantic import BaseModel

from novacommerce.api.errors import APIError
from novacommerce.idempotency import (
    WriteExecution,
    WriteOutcome,
    _json_value,
    request_fingerprint,
    validate_idempotency_key,
    write_response,
)

CUSTOMER = UUID("00000000-0000-0000-0000-000000000001")
TARGET = UUID("00000000-0000-0000-0000-000000000002")


@pytest.mark.parametrize("value", [None, ""])
def test_missing_idempotency_key_is_a_400(value: str | None) -> None:
    with pytest.raises(APIError, match="required") as caught:
        validate_idempotency_key(value)
    assert caught.value.status_code == 400
    assert caught.value.code == "idempotency_key_required"


@pytest.mark.parametrize("value", ["short", "x" * 256, "bad key", "ümlaut"])
def test_malformed_idempotency_key_is_a_422(value: str) -> None:
    with pytest.raises(APIError) as caught:
        validate_idempotency_key(value)
    assert caught.value.status_code == 422
    assert caught.value.code == "invalid_idempotency_key"


def test_valid_idempotency_key_is_returned_unchanged() -> None:
    key = "m2d.order.create:2026-08-21"
    assert validate_idempotency_key(key) == key


def test_fingerprint_ignores_json_whitespace_and_body_key_order() -> None:
    left = request_fingerprint(
        "order.create", CUSTOMER, target_ids=(TARGET,), body={"b": 2, "a": [1, 2]}
    )
    right = request_fingerprint(
        "order.create", CUSTOMER, target_ids=(TARGET,), body={"a": [1, 2], "b": 2}
    )
    assert left == right


def test_fingerprint_changes_for_operation_customer_target_and_body() -> None:
    baseline = request_fingerprint("order.cancel", CUSTOMER, target_ids=(TARGET,), body={})
    assert baseline == request_fingerprint("order.cancel", CUSTOMER, target_ids=(TARGET,), body={})
    assert baseline != request_fingerprint(
        "order.reschedule", CUSTOMER, target_ids=(TARGET,), body={}
    )
    assert baseline != request_fingerprint(
        "order.cancel", UUID(int=3), target_ids=(TARGET,), body={}
    )
    assert baseline != request_fingerprint(
        "order.cancel", CUSTOMER, target_ids=(UUID(int=4),), body={}
    )
    assert baseline != request_fingerprint(
        "order.cancel", CUSTOMER, target_ids=(TARGET,), body={"x": 1}
    )


def test_fingerprint_canonicalizes_uuid_decimal_datetime_models_and_nested_values() -> None:
    class Payload(BaseModel):
        amount: Decimal

    value: dict[str, Any] = {
        "uuid": CUSTOMER,
        "amount": Decimal("12.30"),
        "at": datetime(2026, 8, 21, 12, tzinfo=UTC),
        "model": Payload(amount=Decimal("1.20")),
        "nested": (TARGET,),
    }
    normalized = _json_value(value)
    assert normalized["uuid"] == str(CUSTOMER)
    assert normalized["amount"] == "12.30"
    assert normalized["at"].endswith("+00:00")
    assert normalized["model"] == {"amount": "1.20"}
    assert normalized["nested"] == [str(TARGET)]


@pytest.mark.asyncio
async def test_write_response_marks_replays_without_exposing_extra_data() -> None:
    execution = WriteExecution(WriteOutcome(201, {"id": str(TARGET)}), replayed=True)
    response = write_response(execution)
    assert response.status_code == 201
    assert response.headers["X-Idempotent-Replay"] == "true"
    assert response.body == b'{"id":"00000000-0000-0000-0000-000000000002"}'
