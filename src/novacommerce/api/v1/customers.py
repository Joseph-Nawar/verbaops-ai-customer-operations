"""Customer-owned customer read endpoint."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from novacommerce.api.dependencies import get_database_session
from novacommerce.api.errors import APIError
from novacommerce.api.v1.dependencies import customer_dependency
from novacommerce.auth.context import TrustedCustomerContext
from novacommerce.schemas.customers import CustomerResponse
from novacommerce.services.customers import get_owned_customer

router = APIRouter(tags=["customers"])


@router.get("/customers/{customer_id}", response_model=CustomerResponse)
async def get_customer(
    customer_id: UUID,
    context: Annotated[TrustedCustomerContext, Depends(customer_dependency)],
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> CustomerResponse:
    customer = await get_owned_customer(session, customer_id, context.customer_id)
    if customer is None:
        raise APIError(404, "resource_not_found", "Resource not found.")
    return CustomerResponse.model_validate(customer)
