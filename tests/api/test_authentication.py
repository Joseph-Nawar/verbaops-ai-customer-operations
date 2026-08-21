"""HTTP authentication-boundary tests."""

from typing import Annotated

import pytest
from fastapi import Depends, FastAPI

from verbaops.api.dependencies import get_trusted_context
from verbaops.auth.context import TrustedContext

from .conftest import request


def add_protected_route(app: FastAPI) -> None:
    @app.get("/test/protected")
    async def protected(
        context: Annotated[TrustedContext, Depends(get_trusted_context)],
    ) -> dict[str, str | list[str] | None]:
        return {
            "principal_id": str(context.principal_id),
            "tenant_id": str(context.tenant_id),
            "customer_id": str(context.customer_id) if context.customer_id else None,
            "roles": sorted(role.value for role in context.roles),
        }


@pytest.mark.asyncio
async def test_valid_bearer_returns_server_mapped_context(app: FastAPI) -> None:
    add_protected_route(app)

    response = await request(
        app,
        "GET",
        "/test/protected",
        headers={"Authorization": "Bearer opaque-test-credential"},
    )

    assert response.status_code == 200
    assert response.json()["tenant_id"] == "30000000-0000-0000-0000-000000000002"
    assert response.json()["customer_id"] == "30000000-0000-0000-0000-000000000003"
    assert response.json()["roles"] == ["support_agent"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer unknown-credential"},
        {"Authorization": "Basic opaque-test-credential"},
    ],
)
async def test_missing_or_invalid_bearer_is_generic_401(
    app: FastAPI,
    headers: dict[str, str],
) -> None:
    add_protected_route(app)

    response = await request(app, "GET", "/test/protected", headers=headers)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"]["message"] == "authentication failed"
    assert "unknown-credential" not in response.text
    assert "opaque-test-credential" not in response.text
    assert response.json()["error"]["request_id"]


@pytest.mark.asyncio
async def test_client_identity_headers_cannot_override_trusted_context(app: FastAPI) -> None:
    add_protected_route(app)

    response = await request(
        app,
        "GET",
        "/test/protected",
        headers={
            "Authorization": "Bearer opaque-test-credential",
            "X-Tenant-ID": "90000000-0000-0000-0000-000000000001",
            "X-Customer-ID": "90000000-0000-0000-0000-000000000002",
            "X-Role": "tenant_admin",
        },
    )

    assert response.status_code == 200
    assert response.json()["tenant_id"] == "30000000-0000-0000-0000-000000000002"
    assert response.json()["customer_id"] == "30000000-0000-0000-0000-000000000003"
    assert response.json()["roles"] == ["support_agent"]
