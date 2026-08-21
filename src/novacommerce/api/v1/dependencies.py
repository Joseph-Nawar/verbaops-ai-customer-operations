"""Request dependencies shared by versioned routes."""

from typing import Annotated

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from novacommerce.api.dependencies import get_database_session
from novacommerce.auth.context import TrustedCustomerContext, parse_customer_context
from novacommerce.auth.service import authenticate_service_token, service_bearer
from novacommerce.config.settings import Settings


def _settings(request: Request) -> Settings:
    settings = request.app.state.novacommerce_settings
    if not isinstance(settings, Settings):
        raise RuntimeError("NovaCommerce settings are not configured")
    return settings


async def service_dependency(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(service_bearer)],
) -> str:
    return authenticate_service_token(_settings(request), credentials)


async def customer_dependency(
    request: Request,
    _: Annotated[str, Depends(service_dependency)],
    customer_header: Annotated[str | None, Header(alias="X-VerbaOps-Customer-ID")] = None,
) -> TrustedCustomerContext:
    del request
    return parse_customer_context(customer_header)


DatabaseSession = Annotated[AsyncSession, Depends(get_database_session)]
