"""Authenticated internal tenant currency endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends

from novacommerce.api.v1.dependencies import tenant_currency_dependency
from novacommerce.schemas.writes import TenantCurrencyResponse

router = APIRouter(tags=["tenant-config"])


@router.get("/tenant-config/currency", response_model=TenantCurrencyResponse)
def get_tenant_currency(
    currency_code: Annotated[str, Depends(tenant_currency_dependency)],
) -> TenantCurrencyResponse:
    """Return the one canonical currency configured by NovaCommerce."""

    return TenantCurrencyResponse(currency_code=currency_code)
