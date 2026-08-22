"""FastAPI contract tests for M2D write routes."""

from collections.abc import AsyncIterator, Callable
from typing import cast
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from novacommerce.api.app import create_app
from novacommerce.api.dependencies import get_database_session
from novacommerce.config.settings import Settings

TOKEN = "m2d-api-token-" + "x" * 32
CUSTOMER = UUID("00000000-0000-0000-0000-000000000001")
PRODUCT = UUID("00000000-0000-0000-0000-000000000002")


def make_app() -> FastAPI:
    construct = cast(Callable[..., Settings], Settings)
    app = create_app(settings=construct(_env_file=None, service_token=SecretStr(TOKEN)))

    async def fake_session() -> AsyncIterator[object]:
        yield object()

    app.dependency_overrides[get_database_session] = fake_session
    return app


async def post(
    app: FastAPI,
    path: str,
    *,
    body: object | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, json=body, headers=headers)


def auth_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {TOKEN}",
        "X-VerbaOps-Customer-ID": str(CUSTOMER),
    }


def test_openapi_contains_exactly_the_six_m2d_post_routes() -> None:
    paths = create_app(
        settings=cast(Callable[..., Settings], Settings)(
            _env_file=None, service_token=SecretStr(TOKEN)
        )
    ).openapi()["paths"]
    posts = {path for path, methods in paths.items() if "post" in methods}
    assert posts == {
        "/v1/orders",
        "/v1/orders/{order_id}/cancel",
        "/v1/orders/{order_id}/reschedule",
        "/v1/returns",
        "/v1/orders/{order_id}/refunds",
        "/v1/support-tickets",
    }


@pytest.mark.asyncio
async def test_missing_and_invalid_idempotency_key_are_distinct_contract_errors() -> None:
    app = make_app()
    base = auth_headers()
    body = {"items": [{"product_id": str(PRODUCT), "quantity": 1}]}
    missing = await post(app, "/v1/orders", body=body, headers=base)
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "idempotency_key_required"
    invalid_headers = {**base, "Idempotency-Key": "bad key"}
    invalid = await post(app, "/v1/orders", body=body, headers=invalid_headers)
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "invalid_idempotency_key"


@pytest.mark.asyncio
async def test_write_routes_keep_authentication_and_customer_context_guards() -> None:
    app = make_app()
    missing_auth = await post(
        app,
        "/v1/orders",
        body={"items": [{"product_id": str(PRODUCT), "quantity": 1}]},
        headers={"Idempotency-Key": "m2d-key-001"},
    )
    assert missing_auth.status_code == 401
    no_customer = await post(
        app,
        "/v1/orders",
        body={"items": [{"product_id": str(PRODUCT), "quantity": 1}]},
        headers={"Authorization": f"Bearer {TOKEN}", "Idempotency-Key": "m2d-key-002"},
    )
    assert no_customer.status_code == 400
    assert no_customer.json()["error"]["code"] == "customer_context_required"
