"""Pure-ASGI request and correlation context tests."""

import asyncio
from uuid import UUID

import pytest
from fastapi import FastAPI

from relayai.observability.context import get_request_context

from .conftest import request


def add_context_route(app: FastAPI) -> None:
    @app.get("/test/context/{delay}")
    async def context_route(delay: float) -> dict[str, str | None]:
        await asyncio.sleep(delay)
        context = get_request_context()
        return {
            "request_id": str(context.request_id) if context.request_id else None,
            "correlation_id": str(context.correlation_id) if context.correlation_id else None,
            "tenant_id": str(context.tenant_id) if context.tenant_id else None,
        }


@pytest.mark.asyncio
async def test_request_id_is_generated_and_incoming_value_is_ignored(app: FastAPI) -> None:
    response = await request(
        app,
        "GET",
        "/health",
        headers={"X-Request-ID": "90000000-0000-0000-0000-000000000001"},
    )

    request_id = UUID(response.headers["X-Request-ID"])
    assert request_id != UUID("90000000-0000-0000-0000-000000000001")


@pytest.mark.asyncio
async def test_correlation_id_is_generated_preserved_or_replaced(app: FastAPI) -> None:
    generated = await request(app, "GET", "/health")
    preserved_value = "90000000-0000-0000-0000-000000000002"
    preserved = await request(
        app,
        "GET",
        "/health",
        headers={"X-Correlation-ID": preserved_value},
    )
    replaced = await request(
        app,
        "GET",
        "/health",
        headers={"X-Correlation-ID": "not-a-uuid"},
    )

    assert UUID(generated.headers["X-Correlation-ID"])
    assert preserved.headers["X-Correlation-ID"] == preserved_value
    assert UUID(replaced.headers["X-Correlation-ID"])
    assert replaced.headers["X-Correlation-ID"] != "not-a-uuid"


@pytest.mark.asyncio
async def test_request_context_does_not_leak_between_sequential_requests(app: FastAPI) -> None:
    add_context_route(app)

    first = await request(app, "GET", "/test/context/0")
    second = await request(app, "GET", "/test/context/0")

    assert first.json()["request_id"] == first.headers["X-Request-ID"]
    assert second.json()["request_id"] == second.headers["X-Request-ID"]
    assert first.json()["request_id"] != second.json()["request_id"]
    assert get_request_context().request_id is None
    assert get_request_context().correlation_id is None
    assert get_request_context().tenant_id is None


@pytest.mark.asyncio
async def test_concurrent_requests_retain_isolated_contexts(app: FastAPI) -> None:
    add_context_route(app)

    first, second = await asyncio.gather(
        request(app, "GET", "/test/context/0.03"),
        request(app, "GET", "/test/context/0"),
    )

    assert first.json()["request_id"] == first.headers["X-Request-ID"]
    assert second.json()["request_id"] == second.headers["X-Request-ID"]
    assert first.json()["request_id"] != second.json()["request_id"]
    assert first.json()["correlation_id"] == first.headers["X-Correlation-ID"]
    assert second.json()["correlation_id"] == second.headers["X-Correlation-ID"]
