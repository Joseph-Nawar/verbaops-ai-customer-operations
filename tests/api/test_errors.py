"""HTTP error-envelope tests."""

from typing import Annotated

import pytest
from fastapi import FastAPI, Query

from .conftest import request


def add_error_routes(app: FastAPI) -> None:
    @app.get("/test/explode")
    async def explode() -> None:
        raise RuntimeError("internal exception detail must not reach client")

    @app.get("/test/validated")
    async def validated(value: Annotated[int, Query()]) -> dict[str, int]:
        return {"value": value}


@pytest.mark.asyncio
async def test_unhandled_exception_is_generic_and_has_request_id(app: FastAPI) -> None:
    add_error_routes(app)

    response = await request(app, "GET", "/test/explode")

    assert response.status_code == 500
    assert response.json()["error"]["message"] == "internal server error"
    assert "internal exception detail" not in response.text
    assert response.json()["error"]["request_id"]
    assert response.headers["X-Request-ID"] == response.json()["error"]["request_id"]


@pytest.mark.asyncio
async def test_validation_error_omits_sensitive_input_reflection(app: FastAPI) -> None:
    add_error_routes(app)

    response = await request(app, "GET", "/test/validated?value=sensitive-input")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_validation_error"
    assert "sensitive-input" not in response.text
    assert response.json()["error"]["request_id"]


@pytest.mark.asyncio
async def test_expected_http_error_is_not_converted_to_internal_error(app: FastAPI) -> None:
    response = await request(app, "GET", "/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "http_error"
    assert response.json()["error"]["request_id"]
