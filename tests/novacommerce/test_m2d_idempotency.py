"""Pure M2D idempotency contracts."""

from uuid import UUID

import pytest

from novacommerce.api.errors import APIError
from novacommerce.idempotency import request_fingerprint, validate_idempotency_key

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
