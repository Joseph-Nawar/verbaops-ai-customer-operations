"""Stage 6 exact-resource read contracts."""

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

TOKEN = "stage6-exact-read-contract-token-" + "x" * 32
RESOURCE_ID = UUID("00000000-0000-0000-0000-000000000001")


def make_app() -> FastAPI:
    construct = cast(Callable[..., Settings], Settings)
    app = create_app(settings=construct(_env_file=None, service_token=SecretStr(TOKEN)))

    async def fake_session() -> AsyncIterator[object]:
        yield object()

    app.dependency_overrides[get_database_session] = fake_session
    return app


@pytest.mark.asyncio
async def test_exact_read_routes_are_the_only_return_and_ticket_reads() -> None:
    app = make_app()
    paths = app.openapi()["paths"]

    assert (
        paths["/v1/returns/{return_id}"]["get"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        == "#/components/schemas/ReturnResponse"
    )
    assert (
        paths["/v1/support-tickets/{ticket_id}"]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]["$ref"]
        == "#/components/schemas/SupportTicketResponse"
    )
    assert set(paths["/v1/returns"]) == {"post"}
    assert set(paths["/v1/support-tickets"]) == {"post"}
    assert not any(
        path.startswith("/v1/returns/") for path in paths if path != "/v1/returns/{return_id}"
    )
    assert not any(
        path.startswith("/v1/support-tickets/")
        for path in paths
        if path != "/v1/support-tickets/{ticket_id}"
    )


@pytest.mark.asyncio
async def test_exact_reads_require_the_existing_internal_service_authentication() -> None:
    app = make_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/v1/returns/{RESOURCE_ID}")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"
