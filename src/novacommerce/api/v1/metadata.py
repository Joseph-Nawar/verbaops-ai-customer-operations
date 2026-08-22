"""Reusable OpenAPI metadata for authenticated write routes."""

from typing import Any


def _customer_header() -> dict[str, Any]:
    return {
        "name": "X-VerbaOps-Customer-ID",
        "in": "header",
        "required": True,
        "schema": {"type": "string", "format": "uuid"},
    }


def _idempotency_header() -> dict[str, Any]:
    return {
        "name": "Idempotency-Key",
        "in": "header",
        "required": True,
        "schema": {
            "type": "string",
            "minLength": 8,
            "maxLength": 255,
            "pattern": r"^[A-Za-z0-9._:-]{8,255}$",
        },
    }


def customer_openapi_extra() -> dict[str, Any]:
    """Describe the trusted customer header without changing its dependency."""

    return {"parameters": [_customer_header()]}


def write_openapi_extra() -> dict[str, Any]:
    """Describe headers while keeping runtime validation dependencies optional."""

    return {"parameters": [_customer_header(), _idempotency_header()]}
