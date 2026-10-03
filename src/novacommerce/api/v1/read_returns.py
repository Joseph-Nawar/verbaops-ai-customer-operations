"""Customer-scoped exact return read-back."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from novacommerce.api.errors import APIError
from novacommerce.api.v1.dependencies import DatabaseSession, customer_dependency
from novacommerce.auth.context import TrustedCustomerContext
from novacommerce.db.models.order import Order
from novacommerce.db.models.return_ import Return
from novacommerce.schemas.writes import ReturnResponse

router = APIRouter(tags=["reads"])


@router.get("/returns/{return_id}", response_model=ReturnResponse)
async def get_return(
    return_id: UUID,
    session: DatabaseSession,
    context: Annotated[TrustedCustomerContext, Depends(customer_dependency)],
) -> ReturnResponse:
    """Return one exact return owned by the authenticated customer."""

    record = (
        await session.execute(
            select(Return)
            .join(Order, Return.order_id == Order.id)
            .where(Return.id == return_id, Order.customer_id == context.customer_id)
            .options(selectinload(Return.items))
        )
    ).scalar_one_or_none()
    if record is None:
        raise APIError(404, "resource_not_found", "Resource not found.")
    return ReturnResponse.model_validate(record)
