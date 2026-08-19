"""Shared HTTP test fixtures."""

from collections.abc import Callable, Mapping
from typing import cast
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI

from relayai.auth.context import Role, TrustedContext
from relayai.auth.development import DevelopmentAuthProvider
from relayai.auth.provider import OpaqueCredential
from relayai.config.settings import Environment, Settings


def build_settings() -> Settings:
    construct = cast(Callable[..., Settings], Settings)
    return construct(_env_file=None)


def build_context(
    *,
    principal_id: str = "30000000-0000-0000-0000-000000000001",
    tenant_id: str = "30000000-0000-0000-0000-000000000002",
    customer_id: str | None = "30000000-0000-0000-0000-000000000003",
) -> TrustedContext:
    return TrustedContext(
        principal_id=UUID(principal_id),
        tenant_id=UUID(tenant_id),
        customer_id=UUID(customer_id) if customer_id is not None else None,
        roles=frozenset({Role.SUPPORT_AGENT}),
    )


def build_provider(
    context: TrustedContext | None = None,
    *,
    environment: Environment = Environment.TEST,
) -> DevelopmentAuthProvider:
    mapped_context = context or build_context()
    return DevelopmentAuthProvider(
        {OpaqueCredential("opaque-test-credential"): mapped_context},
        environment=environment,
    )


@pytest.fixture
def trusted_context() -> TrustedContext:
    return build_context()


@pytest.fixture
def auth_provider(trusted_context: TrustedContext) -> DevelopmentAuthProvider:
    return build_provider(trusted_context)


@pytest.fixture
def settings() -> Settings:
    return build_settings()


@pytest.fixture
def app(
    settings: Settings,
    auth_provider: DevelopmentAuthProvider,
) -> FastAPI:
    from relayai.api.app import create_app

    return create_app(settings=settings, auth_provider=auth_provider)


async def request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    headers: Mapping[str, str] | None = None,
    json: object | None = None,
    lifespan: bool = True,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        if not lifespan:
            return await client.request(method, path, headers=headers, json=json)
        async with app.router.lifespan_context(app):
            return await client.request(method, path, headers=headers, json=json)
